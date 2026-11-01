from pathlib import Path

import pytest

from app.analysis import calculate_score, evidence_confidence, recommendation_for, validate_citations
from app.models import DimensionScore, Evidence
from app.sources import SOURCE_REGISTRY, SourcePolicyError, load_candidates, validate_public_url


FIXTURE = Path(__file__).parent / "fixtures" / "yc.json"


def test_yc_filter_normalizes_batch_and_topic() -> None:
    candidates = load_candidates(FIXTURE, topic="AI agents for SMBs", batch="W25", limit=10)
    assert [candidate.slug for candidate in candidates] == ["agentdesk"]


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
