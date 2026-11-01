from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from app.analysis.service import (
    _normalize_changes_mind,
    _normalize_confidence,
    _normalize_recommendation,
    _normalize_score,
    synthesize,
)
from app.domain.enums import AIProvider, AnalysisMode, Recommendation
from app.domain.models import Candidate, Evidence


NOW = datetime(2026, 8, 24, tzinfo=timezone.utc)


def _candidate() -> Candidate:
    return Candidate(
        slug="agentflow",
        name="AgentFlow",
        website="https://agentflow.example",
        one_liner="AI workflows for SMBs",
        description="Workflow automation platform",
        batch="Summer 2026",
        source_url="https://source.example",
    )


def _evidence() -> list[Evidence]:
    return [
        Evidence(
            id="ev-001",
            claim="Product launched in 2026",
            excerpt="AgentFlow launched its SMB workflow automation tool.",
            source_url="https://news.example/agentflow",
            source_title="TechNews",
            source_type="yc_directory",
            trust_tier="canonical",
            verification="first_party",
        ),
        Evidence(
            id="ev-002",
            claim="Traction milestone",
            excerpt="AgentFlow reached $50k ARR with 20 customers.",
            source_url="https://news.example/traction",
            source_title="TractionUpdate",
            source_type="yc_directory",
            trust_tier="open_web",
            verification="third_party",
        ),
    ]


def test_normalize_confidence() -> None:
    # 0 to 1 float values
    assert _normalize_confidence(0.85) == 0.85
    assert _normalize_confidence(0.0) == 0.0
    assert _normalize_confidence(1.0) == 1.0

    # Integer 0 to 100 percentages normalized to 0.0 - 1.0
    assert _normalize_confidence(85) == 0.85
    assert _normalize_confidence(100) == 1.0
    assert _normalize_confidence(50) == 0.5

    # Float > 1.0
    assert _normalize_confidence(72.5) == 0.725

    # String percentage
    assert _normalize_confidence("85%") == 0.85
    assert _normalize_confidence(" 0.90 ") == 0.90
    assert _normalize_confidence("95") == 0.95

    # Invalid / None fallback
    assert _normalize_confidence(None) == 0.5
    assert _normalize_confidence("invalid") == 0.5
    assert _normalize_confidence(-10) == 0.0
    assert _normalize_confidence(150) == 1.0


def test_normalize_score() -> None:
    assert _normalize_score(85.5) == 85.5
    assert _normalize_score(0) == 0.0
    assert _normalize_score(100) == 100.0
    assert _normalize_score("78.2") == 78.2
    assert _normalize_score(-10) == 0.0
    assert _normalize_score(150) == 100.0
    assert _normalize_score(None) == 50.0
    assert _normalize_score("invalid") == 50.0


def test_normalize_recommendation() -> None:
    assert _normalize_recommendation(Recommendation.TAKE_A_MEETING) == Recommendation.TAKE_A_MEETING
    assert _normalize_recommendation("Take a meeting") == Recommendation.TAKE_A_MEETING
    assert _normalize_recommendation("take a meeting") == Recommendation.TAKE_A_MEETING
    assert _normalize_recommendation("take_a_meeting") == Recommendation.TAKE_A_MEETING
    assert _normalize_recommendation("meet") == Recommendation.TAKE_A_MEETING

    assert _normalize_recommendation(Recommendation.WATCH) == Recommendation.WATCH
    assert _normalize_recommendation("Watch") == Recommendation.WATCH
    assert _normalize_recommendation("watch") == Recommendation.WATCH
    assert _normalize_recommendation("monitoring") == Recommendation.WATCH

    assert _normalize_recommendation(Recommendation.PASS) == Recommendation.PASS
    assert _normalize_recommendation("Pass") == Recommendation.PASS
    assert _normalize_recommendation("pass") == Recommendation.PASS
    assert _normalize_recommendation("reject") == Recommendation.PASS

    # Default fallback for unknown
    assert _normalize_recommendation("unknown_recommendation") == Recommendation.WATCH
    assert _normalize_recommendation(None) == Recommendation.WATCH


def test_normalize_changes_mind() -> None:
    # 2 items unchanged
    two_items = ["Item 1", "Item 2"]
    assert _normalize_changes_mind(two_items) == two_items

    # 3 items unchanged
    three_items = ["Item 1", "Item 2", "Item 3"]
    assert _normalize_changes_mind(three_items) == three_items

    # 1 item padded to 2
    one_item = ["Item 1"]
    padded = _normalize_changes_mind(one_item)
    assert len(padded) == 2
    assert padded[0] == "Item 1"
    assert "retention" in padded[1].lower() or "traction" in padded[1].lower()

    # 0 items filled with 2 reasonable items
    empty_padded = _normalize_changes_mind([])
    assert len(empty_padded) == 2

    # >3 items truncated to 3
    many_items = ["Item 1", "Item 2", "Item 3", "Item 4", "Item 5"]
    truncated = _normalize_changes_mind(many_items)
    assert len(truncated) == 3
    assert truncated == ["Item 1", "Item 2", "Item 3"]

    # String input converted to list with padding
    from_str = _normalize_changes_mind("Single string condition")
    assert len(from_str) == 2
    assert from_str[0] == "Single string condition"


def test_synthesize_normalizes_integer_confidence_and_single_changes_mind() -> None:
    class MockBedrockClient:
        def converse(self, **_kwargs):
            payload = {
                "summary": "AgentFlow automates SMB workflows. [ev-001]",
                "team": "Not disclosed",
                "product": "Agentic automation platform. [ev-001]",
                "market": "SMB software market. [ev-002]",
                "why_now": "Rapid AI LLM advances. [ev-001]",
                "risks": ["Retention risk in competitive market. [ev-002]"],
                "open_questions": ["What is gross margin?"],
                "changes_mind": ["Verified $1M ARR milestone"],  # Only 1 item returned
                "score": "88",  # String score
                "confidence": 85,  # Integer 0-100 confidence
                "recommendation": "take_a_meeting",  # Snake case recommendation
                "citations": ["ev-001", "ev-002"],
            }
            return {"output": {"message": {"content": [{"text": json.dumps(payload)}]}}}

    client = MockBedrockClient()
    analysis = synthesize(
        _candidate(),
        _evidence(),
        httpx.Client(),
        provider=AIProvider.BEDROCK,
        bedrock_client=client,
    )

    assert analysis.company == "AgentFlow"
    assert analysis.score == 88.0
    assert analysis.confidence == 0.85
    assert analysis.recommendation == Recommendation.TAKE_A_MEETING
    assert len(analysis.changes_mind) == 2
    assert analysis.changes_mind[0] == "Verified $1M ARR milestone"
    assert analysis.financials.revenue == "$50k"
    assert "ev-002" in analysis.financials.evidence_ids


def test_synthesize_self_heals_missing_narrative_citations_and_missing_citations_list() -> None:
    class UntaggedPayloadBedrockClient:
        def converse(self, **_kwargs):
            # LLM omitted [ev-XXX] tags and citations list
            payload = {
                "summary": "AgentFlow automates SMB workflows without tags.",
                "team": "Strong founding team from top AI labs.",
                "product": "Agentic automation platform with integrations.",
                "market": "Large underserved SMB market.",
                "why_now": "Rapid AI LLM advances enable reliable action taking.",
                "risks": [
                    "Retention risk in competitive market.",
                    "High initial customer acquisition cost.",
                ],
                "open_questions": ["What is gross margin?"],
                "changes_mind": ["Verified $1M ARR milestone", "5 customer references"],
                "score": 82,
                "confidence": 0.8,
                "recommendation": "Take a meeting",
            }
            return {"output": {"message": {"content": [{"text": json.dumps(payload)}]}}}

    client = UntaggedPayloadBedrockClient()
    analysis = synthesize(
        _candidate(),
        _evidence(),
        httpx.Client(),
        provider=AIProvider.BEDROCK,
        bedrock_client=client,
    )

    # All narrative fields should have been auto-healed with [ev-001]
    assert "[ev-001]" in analysis.summary
    assert "[ev-001]" in analysis.team
    assert "[ev-001]" in analysis.product
    assert "[ev-001]" in analysis.market
    assert "[ev-001]" in analysis.why_now
    assert all("[ev-001]" in r for r in analysis.risks)
    assert analysis.score == 82.0
    assert analysis.recommendation == Recommendation.TAKE_A_MEETING

