from collections.abc import Mapping
from typing import Any

from app.domain.enums import Recommendation
from app.domain.models import Evidence

THESIS = (
    "Pre-seed and seed B2B AI companies that replace a frequent, expensive SMB "
    "workflow, show value quickly, and compound an advantage through integrations, data, or distribution."
)

DIMENSION_WEIGHTS = {
    "workflow_pain": 25,
    "speed_to_value": 20,
    "compounding_advantage": 20,
    "team_execution": 15,
    "market_distribution": 20,
}


def normalize_dimensions(
    value: object, evidence: list[Evidence]
) -> tuple[list[dict[str, Any]], float, Recommendation] | None:
    """Validate model dimensions and derive the only authoritative total."""
    if value in (None, []):
        return None
    if not isinstance(value, list) or len(value) != len(DIMENSION_WEIGHTS):
        raise ValueError("dimensions must contain the five required scoring dimensions")

    valid_ids = {item.id for item in evidence}
    by_name: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("each scoring dimension must be an object")
        name = item.get("name")
        if not isinstance(name, str) or name not in DIMENSION_WEIGHTS or name in by_name:
            raise ValueError("dimensions must contain each required name exactly once")
        score = item.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 10:
            raise ValueError(f"dimension {name} score must be between 0 and 10")
        if item.get("weight") != DIMENSION_WEIGHTS[name]:
            raise ValueError(f"dimension {name} weight must be {DIMENSION_WEIGHTS[name]}")
        rationale = item.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError(f"dimension {name} requires a rationale")
        evidence_ids = item.get("evidence_ids")
        if not isinstance(evidence_ids, list) or any(
            not isinstance(evidence_id, str) or evidence_id not in valid_ids
            for evidence_id in evidence_ids
        ):
            raise ValueError(f"dimension {name} contains an unknown evidence ID")
        if evidence and not evidence_ids:
            raise ValueError(f"dimension {name} requires at least one evidence ID")
        by_name[name] = {
            "name": name,
            "score": float(score),
            "weight": DIMENSION_WEIGHTS[name],
            "rationale": rationale.strip(),
            "evidence_ids": evidence_ids,
        }

    dimensions = [by_name[name] for name in DIMENSION_WEIGHTS]
    total = sum(item["score"] * item["weight"] for item in dimensions) / 10
    recommendation = (
        Recommendation.TAKE_A_MEETING
        if total >= 70
        else Recommendation.WATCH
        if total >= 45
        else Recommendation.PASS
    )
    return dimensions, total, recommendation


def validate_citations(ids: list[str], evidence: list[Evidence]) -> None:
    if evidence and not ids:
        raise ValueError("at least one evidence citation is required")
    valid = {item.id for item in evidence}
    missing = set(ids) - valid
    if missing:
        raise ValueError(f"Unknown evidence IDs: {', '.join(sorted(missing))}")
