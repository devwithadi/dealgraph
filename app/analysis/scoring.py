from app.domain.models import Evidence

THESIS = (
    "Pre-seed and seed B2B AI companies that replace a frequent, expensive SMB "
    "workflow, show value quickly, and compound an advantage through integrations, data, or distribution."
)


def validate_citations(ids: list[str], evidence: list[Evidence]) -> None:
    if evidence and not ids:
        raise ValueError("at least one evidence citation is required")
    valid = {item.id for item in evidence}
    missing = set(ids) - valid
    if missing:
        raise ValueError(f"Unknown evidence IDs: {', '.join(sorted(missing))}")
