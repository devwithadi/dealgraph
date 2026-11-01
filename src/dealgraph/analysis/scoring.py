"""Public deterministic scoring API."""

from dealgraph.analysis.service import (
    calculate_score,
    evidence_confidence,
    recommendation_for,
    validate_citations,
)

__all__ = [
    "calculate_score",
    "evidence_confidence",
    "recommendation_for",
    "validate_citations",
]
