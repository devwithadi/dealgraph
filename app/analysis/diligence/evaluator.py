from __future__ import annotations

from app.analysis.diligence.constants import DILIGENCE
from app.analysis.diligence.models import DiligenceEvaluation, DiligencePillar
from app.analysis.providers import model_json
from app.domain.enums import AIProvider
from app.domain.models import Candidate, Evidence
from app.prompts.diligence import build_diligence_prompt


def evaluate_diligence(
    candidate: Candidate,
    evidence: list[Evidence],
    topic: str,
    hop: int,
    *,
    provider: AIProvider,
    model: str,
) -> DiligenceEvaluation:
    """Ask the configured model for typed evidence gaps and follow-up queries."""
    payload = model_json(
        build_diligence_prompt(candidate, evidence, topic, hop),
        provider=provider,
        model=model,
        max_tokens=DILIGENCE.evaluation_max_tokens,
        stage=DILIGENCE.evaluation_stage,
    )
    evaluation = DiligenceEvaluation.model_validate(payload)

    expected_pillars = set(DiligencePillar.core())
    returned_pillars = [gap.pillar for gap in evaluation.gaps]
    if len(returned_pillars) != len(set(returned_pillars)) or set(returned_pillars) != expected_pillars:
        raise ValueError("diligence evaluation must contain each core pillar exactly once")

    evidence_ids = {item.id for item in evidence}
    for gap in evaluation.gaps:
        if gap.resolved and gap.resolved_by_evidence_id not in evidence_ids:
            raise ValueError("resolved diligence gaps must cite supplied evidence")

    unresolved_pillars = {gap.pillar for gap in evaluation.gaps if not gap.resolved}
    if any(query.pillar not in unresolved_pillars or query.hop != hop for query in evaluation.followup_queries):
        raise ValueError("follow-up queries must target unresolved pillars at the requested hop")
    query_pillars = [query.pillar for query in evaluation.followup_queries]
    if len(query_pillars) != len(set(query_pillars)):
        raise ValueError("diligence evaluation allows one follow-up query per unresolved pillar")
    return evaluation
