from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from app.analysis.service import (
    _evidence_confidence,
    _normalize_changes_mind,
    synthesize,
)
from app.domain.enums import AIProvider, AnalysisMode, CitationTag, Recommendation
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
            status=CitationTag.VERIFIED,
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


def test_evidence_confidence_is_deterministic_and_rewards_independent_coverage() -> None:
    yc = _evidence()[0].model_copy(update={"status": CitationTag.VERIFIED})
    company = _evidence()[1].model_copy(
        update={
            "source_url": "https://agentflow.example/pricing",
            "source_type": "company_website",
            "status": CitationTag.CLAIMED,
        }
    )
    independent = _evidence()[1].model_copy(
        update={
            "source_url": "https://independent.example/review",
            "source_type": "agent_reach",
            "status": CitationTag.TRUSTED,
        }
    )

    assert _evidence_confidence([yc, company]) == 0.6
    same_company_pages = [
        company.model_copy(
            update={"id": f"ev-{index:03d}", "source_url": f"https://agentflow.example/page-{index}"}
        )
        for index in range(2, 7)
    ]
    assert _evidence_confidence([yc, *same_company_pages]) == 0.65
    assert _evidence_confidence([yc, company, independent]) == 1.0
    assert _evidence_confidence([yc, company, independent]) == _evidence_confidence(
        [yc, company, independent]
    )


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


def test_synthesize_preserves_thesis_and_recomputes_dimension_score() -> None:
    class MockBedrockClient:
        def converse(self, **_kwargs):
            payload = {
                "thesis": "AgentFlow owns the SMB workflow layer through embedded integrations [ev-001].",
                "summary": "AgentFlow automates SMB workflows. [ev-001]",
                "team": "Not disclosed",
                "product": "Agentic automation platform. [ev-001]",
                "market": "SMB software market. [ev-002]",
                "why_now": "Rapid AI LLM advances. [ev-001]",
                "risks": ["Retention risk in competitive market. [ev-002]"],
                "open_questions": ["What is gross margin?"],
                "changes_mind": ["Verified $1M ARR milestone"],  # Only 1 item returned
                "score": "12",  # Deliberately contradictory; runtime recomputes it.
                "dimensions": [
                    {"name": "workflow_pain", "score": 9, "weight": 25, "rationale": "Frequent support work [ev-001]", "evidence_ids": ["ev-001"]},
                    {"name": "speed_to_value", "score": 8, "weight": 20, "rationale": "Fast deployment [ev-001]", "evidence_ids": ["ev-001"]},
                    {"name": "compounding_advantage", "score": 7, "weight": 20, "rationale": "Embedded integrations [ev-001]", "evidence_ids": ["ev-001"]},
                    {"name": "team_execution", "score": 6, "weight": 15, "rationale": "Team details are limited [ev-002]", "evidence_ids": ["ev-002"]},
                    {"name": "market_distribution", "score": 8, "weight": 20, "rationale": "Large SMB market [ev-002]", "evidence_ids": ["ev-002"]},
                ],
                "confidence": 85,  # Integer 0-100 confidence
                "recommendation": "pass",  # Deliberately contradictory.
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
    assert analysis.thesis == (
        "AgentFlow owns the SMB workflow layer through embedded integrations [ev-001]."
    )
    assert analysis.score == 77.5
    assert analysis.confidence == 0.35
    assert analysis.recommendation == Recommendation.TAKE_A_MEETING
    assert [item["name"] for item in analysis.dimensions] == [
        "workflow_pain",
        "speed_to_value",
        "compounding_advantage",
        "team_execution",
        "market_distribution",
    ]
    assert len(analysis.changes_mind) == 2
    assert analysis.changes_mind[0] == "Verified $1M ARR milestone"
    assert analysis.financials.revenue == "$50k"
    assert "ev-002" in analysis.financials.evidence_ids


def test_synthesize_rejects_payload_without_scoring_dimensions() -> None:
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
    with pytest.raises(ValueError, match="five required scoring dimensions"):
        synthesize(
            _candidate(),
            _evidence(),
            httpx.Client(),
            provider=AIProvider.BEDROCK,
            bedrock_client=client,
        )
