from datetime import datetime, timezone

import pytest

from app.analysis.scoring import normalize_dimensions
from app.domain.enums import Recommendation
from app.domain.models import Evidence


def _evidence() -> list[Evidence]:
    return [
        Evidence(
            id="ev-001",
            claim="Evidence",
            excerpt="Evidence excerpt",
            source_url="https://example.com/evidence",
            source_title="Example",
            source_type="open_web",
            trust_tier="open_web",
            verification="third_party",
            retrieved_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        )
    ]


def _dimensions() -> list[dict[str, object]]:
    return [
        {
            "name": name,
            "score": 5,
            "weight": weight,
            "rationale": "Supported reason [ev-001]",
            "evidence_ids": ["ev-001"],
        }
        for name, weight in (
            ("workflow_pain", 25),
            ("speed_to_value", 20),
            ("compounding_advantage", 20),
            ("team_execution", 15),
            ("market_distribution", 20),
        )
    ]


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"score": 11}, "score must be between 0 and 10"),
        ({"weight": 99}, "weight must be"),
        ({"evidence_ids": ["ev-999"]}, "unknown evidence ID"),
    ],
)
def test_normalize_dimensions_rejects_invalid_model_output(update, message) -> None:
    dimensions = _dimensions()
    dimensions[0] = {**dimensions[0], **update}

    with pytest.raises(ValueError, match=message):
        normalize_dimensions(dimensions, _evidence())


def test_normalize_dimensions_applies_watch_boundary() -> None:
    dimensions = [{**item, "score": 4.5} for item in reversed(_dimensions())]

    normalized = normalize_dimensions(dimensions, _evidence())

    assert normalized is not None
    items, total, recommendation = normalized
    assert [item["name"] for item in items] == [
        "workflow_pain",
        "speed_to_value",
        "compounding_advantage",
        "team_execution",
        "market_distribution",
    ]
    assert total == 45
    assert recommendation == Recommendation.WATCH
