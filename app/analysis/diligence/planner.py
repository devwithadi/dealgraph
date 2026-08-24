from __future__ import annotations

from app.analysis.diligence.models import DiligencePillar, DiligencePlan, SearchQuery
from app.domain.models import Candidate, Evidence


def generate_diligence_plan(
    candidate: Candidate,
    topic: str,
    initial_evidence: list[Evidence] | None = None,
) -> DiligencePlan:
    """Generate a targeted 4-pillar diligence research plan for a candidate."""
    name = candidate.name.strip()
    website = candidate.website.strip()
    industry = candidate.industry.strip() or topic
    one_liner = candidate.one_liner.strip()

    focus_areas = [
        f"Commercial / TAM validation in {industry}",
        f"Unit economics and pricing sustainability for {name}",
        f"Technical differentiation and IP defensibility of {one_liner}",
        f"Key execution and regulatory risks for {name}",
    ]

    queries: list[SearchQuery] = [
        SearchQuery(
            query=f"{name} ({website}) market size target customers competitors commercial traction {topic}",
            pillar=DiligencePillar.COMMERCIAL_TAM.value,
            rationale=f"Validate market demand, competitive landscape, and customer segment for {name}.",
            hop=1,
        ),
        SearchQuery(
            query=f"{name} pricing tiers revenue ARR MRR funding valuation burn unit economics",
            pillar=DiligencePillar.UNIT_ECONOMICS.value,
            rationale=f"Determine pricing structure, monetization model, and historical financing for {name}.",
            hop=1,
        ),
        SearchQuery(
            query=f"{name} tech architecture proprietary models data moat IP defensibility benchmarks",
            pillar=DiligencePillar.TECH_IP.value,
            rationale=f"Assess technological defensibility, proprietary data advantage, and technical moats.",
            hop=1,
        ),
        SearchQuery(
            query=f"{name} customer churn risks compliance regulatory concerns dependencies alternatives",
            pillar=DiligencePillar.RISK_ESG.value,
            rationale=f"Identify regulatory bottlenecks, operational dependencies, and execution risks.",
            hop=1,
        ),
    ]

    return DiligencePlan(
        candidate_slug=candidate.slug,
        candidate_name=candidate.name,
        topic=topic,
        queries=queries,
        focus_areas=focus_areas,
    )
