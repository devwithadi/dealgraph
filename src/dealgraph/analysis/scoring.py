"""Deterministic thesis scoring and evidence validation."""

import re
from datetime import datetime, timezone

from dealgraph.domain.enums import Recommendation
from dealgraph.domain.models import Candidate, DimensionScore, Evidence

THESIS = (
    "Pre-seed and seed B2B AI companies that replace a frequent, expensive SMB "
    "workflow, show value quickly, and compound an advantage through integrations, data, or distribution."
)


def calculate_score(dimensions: list[DimensionScore]) -> float:
    expected = {"pain_roi", "differentiation", "team", "distribution", "market", "traction"}
    if {item.name for item in dimensions} != expected or len(dimensions) != len(expected):
        raise ValueError("dimensions must match the six-part rubric exactly")
    if sum(item.weight for item in dimensions) != 100:
        raise ValueError("dimension weights must total 100")
    return round(sum(item.score * item.weight for item in dimensions) / 100, 1)


def recommendation_for(score: float, confidence: float) -> Recommendation:
    if score >= 75 and confidence >= 0.65:
        return Recommendation.TAKE_A_MEETING
    if score >= 60 or (score >= 75 and confidence < 0.65):
        return Recommendation.WATCH
    return Recommendation.PASS


def validate_citations(ids: list[str], evidence: list[Evidence]) -> None:
    if evidence and not ids:
        raise ValueError("at least one evidence citation is required")
    valid = {item.id for item in evidence}
    missing = set(ids) - valid
    if missing:
        raise ValueError(f"Unknown evidence IDs: {', '.join(sorted(missing))}")


def evidence_confidence(evidence: list[Evidence]) -> float:
    """Independent source types add confidence; extra pages from one source do not."""
    weights = {
        "yc_directory": 0.30,
        "company_website": 0.25,
        "hacker_news": 0.15,
        "regulatory": 0.20,
    }
    source_types = {item.source_type for item in evidence}
    return round(min(0.9, sum(weights.get(source, 0.05) for source in source_types)), 2)


def _contains(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def build_dimensions(candidate: Candidate, evidence: list[Evidence]) -> list[DimensionScore]:
    text = " ".join(
        [candidate.one_liner, candidate.description, *[item.excerpt for item in evidence]]
    ).lower()
    ids = [item.id for item in evidence]
    hn = next((item for item in evidence if item.source_type == "hacker_news"), None)
    hn_match = re.search(r"(\d+) points", hn.claim) if hn else None
    hn_points = int(hn_match.group(1)) if hn_match else 0
    recent = bool(
        candidate.launched_at
        and (datetime.now(timezone.utc) - candidate.launched_at).days <= 1095
    )
    data = [
        ("pain_roi", 20 + 30 * bool(re.search(r"\b\d+%|\$\d+|\b\d+x\b", text)) + 25 * _contains(text, ("pricing", "per month", "customer")) + 25 * _contains(text, ("workflow", "automate", "replace", "save time")), 25, "Recurring pain, quantified ROI, pricing, and customer proof."),
        ("differentiation", 25 + 25 * _contains(text, ("proprietary", "integration", "platform", "api")) + 25 * _contains(text, ("ai", "machine learning", "agent")) + 25 * (len(candidate.description) > 180), 20, "Technical specificity and evidence of a compounding product advantage."),
        ("team", 25 + 30 * (candidate.team_size is not None) + 25 * _contains(text, ("founder", "team", "engineer")) + 20 * candidate.is_hiring, 20, "Public team, technical-depth, and hiring signals."),
        ("distribution", 20 + 20 * bool(candidate.website) + 25 * _contains(text, ("customer", "pricing", "case study")) + 20 * bool(hn) + 15 * candidate.is_hiring, 15, "Observable paths to customers and community attention."),
        ("market", 30 + 25 * bool(candidate.industry) + 25 * _contains(text, ("b2b", "business", "enterprise", "smb")) + 20 * (len(candidate.tags) > 2), 10, "Specific buyer category and plausible expansion surface."),
        ("traction", 15 + 25 * recent + 20 * candidate.is_hiring + min(40, hn_points / 2), 10, "Freshness, hiring, and Hacker News engagement."),
    ]
    return [
        DimensionScore(
            name=name,
            score=min(100, float(score)),
            weight=weight,
            rationale=rationale,
            evidence_ids=ids,
        )
        for name, score, weight, rationale in data
    ]
