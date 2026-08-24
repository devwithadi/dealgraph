import json

from app.analysis.diligence.models import DiligencePillar, GapSeverity


def build_output_contract(hop: int) -> str:
    example = {
        "gaps": [
            {
                "pillar": " | ".join(pillar.value for pillar in DiligencePillar.core()),
                "description": "Specific evidence gap or resolved coverage statement",
                "severity": " | ".join(severity.value for severity in GapSeverity),
                "resolved": False,
                "rationale": "Evidence-grounded explanation",
                "resolved_by_evidence_id": None,
            }
        ],
        "followup_queries": [
            {
                "query": "One focused public-web search query",
                "pillar": "Exact unresolved pillar",
                "rationale": "How this query resolves the gap",
                "hop": hop,
            }
        ],
    }
    return """# DILIGENCE OUTPUT CONTRACT

Return exactly one JSON object and no Markdown, commentary, or extra keys:
""" + json.dumps(example, indent=2)
