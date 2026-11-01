import json

from app.analysis.diligence.models import DiligencePillar
from app.domain.models import Candidate, Evidence
from app.prompts.diligence.guardrails import GUARDRAILS
from app.prompts.diligence.output import build_output_contract
from app.prompts.diligence.persona import PERSONA
from app.prompts.diligence.workflow import WORKFLOW


def build_diligence_prompt(
    candidate: Candidate,
    evidence: list[Evidence],
    topic: str,
    hop: int,
) -> str:
    inputs = json.dumps(
        {
            "candidate": candidate.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "topic": topic,
            "hop": hop,
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    pillar_values = ", ".join(pillar.value for pillar in DiligencePillar.core())
    workflow = WORKFLOW.replace("<input_json>", inputs).replace("<pillar_values>", pillar_values)
    return "\n\n".join((PERSONA, GUARDRAILS, workflow, build_output_contract(hop)))
