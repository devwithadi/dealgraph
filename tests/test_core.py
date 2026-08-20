import json
from pathlib import Path

import httpx
import pytest

from dealgraph.analysis.scoring import (
    calculate_score,
    evidence_confidence,
    recommendation_for,
    validate_citations,
)
from dealgraph.analysis.service import analyze
from dealgraph.core.logging import bind_request_id
from dealgraph.domain.enums import AIProvider, AnalysisMode, Recommendation
from dealgraph.domain.models import Candidate, DimensionScore, Evidence
from pydantic import ValidationError

from dealgraph.sourcing.candidates import load_candidates
from dealgraph.sourcing.evidence import hn_evidence
from dealgraph.sourcing.policy import SourcePolicyError, validate_public_url
from dealgraph.sourcing.registry import SOURCE_REGISTRY


FIXTURE = Path(__file__).parent / "fixtures" / "yc.json"


def test_yc_filter_normalizes_batch_and_topic() -> None:
    candidates = load_candidates(FIXTURE, topic="AI agents for SMBs", batch="W25", limit=10)
    assert [candidate.slug for candidate in candidates] == ["agentdesk"]


def test_closed_business_states_are_string_enums() -> None:
    assert Recommendation.TAKE_A_MEETING.value == "Take a meeting"
    assert AnalysisMode.DETERMINISTIC_FALLBACK.value == "deterministic_fallback"
    assert AIProvider.BEDROCK.value == "bedrock"


@pytest.mark.parametrize("slug", ["../outside", "/tmp/outside", "company/name"])
def test_candidate_slug_cannot_escape_artifact_directory(slug: str) -> None:
    with pytest.raises(ValidationError):
        Candidate(
            slug=slug,
            name="Unsafe",
            website="https://example.com",
            one_liner="AI",
            source_url="https://example.com/source",
        )


def test_weighted_score_and_recommendation_are_deterministic() -> None:
    dimensions = [
        DimensionScore(name="pain_roi", score=80, weight=25, rationale="x"),
        DimensionScore(name="differentiation", score=70, weight=20, rationale="x"),
        DimensionScore(name="team", score=75, weight=20, rationale="x"),
        DimensionScore(name="distribution", score=60, weight=15, rationale="x"),
        DimensionScore(name="market", score=70, weight=10, rationale="x"),
        DimensionScore(name="traction", score=80, weight=10, rationale="x"),
    ]
    assert calculate_score(dimensions) == 73.0
    assert recommendation_for(75, 0.7) == "Take a meeting"
    assert recommendation_for(74.9, 0.9) == "Watch"
    assert recommendation_for(90, 0.4) == "Watch"
    assert recommendation_for(59.9, 0.9) == "Pass"


def test_score_rejects_duplicate_or_incomplete_rubric() -> None:
    duplicate = [
        DimensionScore(name="pain_roi", score=80, weight=50, rationale="x"),
        DimensionScore(name="pain_roi", score=70, weight=50, rationale="x"),
    ]
    with pytest.raises(ValueError, match="rubric"):
        calculate_score(duplicate)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private",
        "http://169.254.169.254/latest/meta-data",
        "https://user:password@example.com",
        "https://example.com:8443",
        "file:///etc/passwd",
        "https://pitchbook.com/profiles/company",
    ],
)
def test_url_policy_rejects_private_or_blocked_targets(url: str) -> None:
    with pytest.raises(SourcePolicyError):
        validate_public_url(url, resolver=lambda _host: ["93.184.216.34"])


def test_citations_must_reference_real_evidence() -> None:
    evidence = [
        Evidence(
            id="ev-001",
            claim="Company is hiring",
            excerpt="We are hiring",
            source_url="https://example.com/jobs",
            source_title="Jobs",
            source_type="company_website",
            trust_tier="self_reported",
            verification="self_reported",
        )
    ]
    validate_citations(["ev-001"], evidence)
    with pytest.raises(ValueError, match="citation"):
        validate_citations([], evidence)
    with pytest.raises(ValueError, match="ev-404"):
        validate_citations(["ev-404"], evidence)


def test_source_registry_disables_licensed_scraping() -> None:
    assert SOURCE_REGISTRY["yc"]["access"] == "public_api"
    assert SOURCE_REGISTRY["pitchbook"]["enabled"] is False
    assert SOURCE_REGISTRY["pitchbook"]["access"] == "licensed_api_only"


def test_confidence_counts_independent_sources_not_page_count() -> None:
    def item(identifier: str, source_type: str) -> Evidence:
        return Evidence(
            id=identifier,
            claim="claim",
            excerpt="excerpt",
            source_url=f"https://example.com/{identifier}",
            source_title="source",
            source_type=source_type,
            trust_tier="test",
            verification="test",
        )

    first_party_only = [item("ev-001", "yc_directory")] + [
        item(f"ev-00{number}", "company_website") for number in range(2, 6)
    ]
    independent = first_party_only + [item("ev-006", "hacker_news")]
    assert evidence_confidence(first_party_only) == 0.55
    assert evidence_confidence(independent) == 0.7


def test_hn_evidence_prefers_matching_candidate_domain() -> None:
    candidate = Candidate(
        slug="agentdesk",
        name="AgentDesk",
        website="https://agentdesk.example",
        one_liner="AI support",
        source_url="https://www.ycombinator.com/companies/agentdesk",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "hn.algolia.com"
        return httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "objectID": "99",
                        "title": "Launch roundup mentions AgentDesk",
                        "url": "https://news.example/roundup",
                        "points": 500,
                        "num_comments": 100,
                        "created_at": "2025-02-01T00:00:00Z",
                    },
                    {
                        "objectID": "42",
                        "title": "Show HN: AgentDesk",
                        "url": "https://agentdesk.example",
                        "points": 83,
                        "num_comments": 21,
                        "created_at": "2025-02-01T00:00:00Z",
                    },
                ]
            },
            request=request,
        )

    evidence = hn_evidence(candidate, httpx.Client(transport=httpx.MockTransport(handler)), 7)
    assert evidence[0].source_url == "https://news.ycombinator.com/item?id=42"
    assert "83 points" in evidence[0].claim


def test_openai_request_keeps_run_request_id(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/custom/v1/")
    bind_request_id("req-openai")
    candidate = Candidate(
        slug="agentdesk",
        name="AgentDesk",
        website="https://agentdesk.example",
        one_liner="AI support",
        source_url="https://www.ycombinator.com/companies/agentdesk",
    )
    evidence = [
        Evidence(
            id="ev-001",
            claim="Product",
            excerpt="AI support product",
            source_url=candidate.source_url,
            source_title="YC",
            source_type="yc_directory",
            trust_tier="curated_directory",
            verification="third_party",
        )
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://gateway.example/custom/v1/chat/completions"
        assert request.headers["x-kong-request-id"] == "req-openai"
        assert request.headers["authorization"] == "Bearer test-key"
        narrative = {
            "summary": "Summary",
            "team": "Unknown",
            "product": "AI support",
            "market": "Unknown",
            "why_now": "Unknown",
            "risks": ["Unknown traction"],
            "open_questions": ["What is retention?"],
            "changes_mind": ["Verified retention"],
            "citations": ["ev-001"],
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(narrative)}}]},
            request=request,
        )

    result = analyze(
        candidate,
        evidence,
        httpx.Client(transport=httpx.MockTransport(handler)),
        provider=AIProvider.OPENAI,
    )

    assert result.analysis_mode == "openai"


def test_bedrock_converse_uses_model_region_and_request_metadata(monkeypatch) -> None:
    monkeypatch.setenv("BEDROCK_MODEL_ID", "amazon.nova-micro-v1:0")
    bind_request_id("req-bedrock")
    candidate = Candidate(
        slug="agentdesk",
        name="AgentDesk",
        website="https://agentdesk.example",
        one_liner="AI support",
        source_url="https://www.ycombinator.com/companies/agentdesk",
    )
    evidence = [
        Evidence(
            id="ev-001",
            claim="Product",
            excerpt="AI support product",
            source_url=candidate.source_url,
            source_title="YC",
            source_type="yc_directory",
            trust_tier="curated_directory",
            verification="third_party",
        )
    ]
    calls: list[dict] = []

    class BedrockClient:
        def converse(self, **kwargs):
            calls.append(kwargs)
            narrative = {
                "summary": "Summary",
                "team": "Unknown",
                "product": "AI support",
                "market": "Unknown",
                "why_now": "Unknown",
                "risks": ["Unknown traction"],
                "open_questions": ["What is retention?"],
                "changes_mind": ["Verified retention"],
                "citations": ["ev-001"],
            }
            return {
                "output": {
                    "message": {"content": [{"text": json.dumps(narrative)}]}
                }
            }

    result = analyze(
        candidate,
        evidence,
        httpx.Client(),
        provider=AIProvider.BEDROCK,
        bedrock_client=BedrockClient(),
    )

    assert result.analysis_mode == "bedrock"
    assert calls[0]["modelId"] == "amazon.nova-micro-v1:0"
    assert calls[0]["requestMetadata"] == {
        "application": "dealgraph",
        "request_id": "req-bedrock",
    }
    assert calls[0]["messages"][0]["role"] == "user"
