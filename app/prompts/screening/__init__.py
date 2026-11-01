import json

from app.analysis.scoring import THESIS
from app.domain.models import Candidate
from app.prompts.screening.guardrails import GUARDRAILS
from app.prompts.screening.output import OUTPUT
from app.prompts.screening.persona import PERSONA
from app.prompts.screening.workflow import WORKFLOW


def build_screening_prompt(candidates: list[Candidate], topic: str) -> str:
    payload = [
        {
            "slug": item.slug,
            "name": item.name,
            "one_liner": item.one_liner,
            "description": item.description,
            "batch": item.batch,
            "industry": item.industry,
            "tags": item.tags,
            "team_size": item.team_size,
            "is_hiring": item.is_hiring,
        }
        for item in candidates
    ]
    inputs = json.dumps(
        {"requested_topic": topic, "investment_thesis": THESIS, "candidates": payload},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return "\n\n".join((PERSONA, GUARDRAILS, WORKFLOW.replace("<input_json>", inputs), OUTPUT))
