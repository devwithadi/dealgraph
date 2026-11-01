import json

from app.prompts.synthesis.guardrails import GUARDRAILS
from app.prompts.synthesis.output import OUTPUT
from app.prompts.synthesis.persona import PERSONA
from app.prompts.synthesis.workflow import WORKFLOW


def build_synthesis_prompt(inputs: dict) -> str:
    input_json = json.dumps(inputs, ensure_ascii=False, indent=2, sort_keys=True)
    return "\n\n".join((PERSONA, GUARDRAILS, WORKFLOW, OUTPUT)).replace(
        "<input_json>", input_json
    )
