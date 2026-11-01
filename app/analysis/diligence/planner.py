from __future__ import annotations

from datetime import datetime, timezone

from app.analysis.diligence.models import DiligencePillar, DiligencePlan, SearchQuery
from app.domain.models import Candidate, Evidence


def generate_diligence_plan(
    candidate: Candidate,
    topic: str,
    initial_evidence: list[Evidence] | None = None,
) -> DiligencePlan:
    """Generate three focused diligence searches for a candidate."""
    name = candidate.name.strip()
    industry = candidate.industry.strip() or topic
    current_year = datetime.now(timezone.utc).year

    focus_areas = [
        f"Founder and team track record for {name}",
        f"Recent traction, customers, revenue, and funding for {name}",
        f"Competition and product differentiation in {industry}",
    ]

    queries: list[SearchQuery] = [
        SearchQuery(
            query=f"{name} founders leadership team background previous companies exits technical experience",
            pillar=DiligencePillar.COMMERCIAL_TAM.value,
            rationale=f"Verify founder and team experience, prior outcomes, and domain credibility for {name}.",
            hop=1,
        ),
        SearchQuery(
            query=f"{name} traction customers revenue ARR funding latest recent {current_year}",
            pillar=DiligencePillar.UNIT_ECONOMICS.value,
            rationale=f"Find current, independently reported commercial traction and financing for {name}.",
            hop=1,
        ),
        SearchQuery(
            query=f"{name} competitors alternatives product differentiation customer reviews {industry} {topic}",
            pillar=DiligencePillar.TECH_IP.value,
            rationale=f"Compare {name} with credible alternatives and test whether its differentiation is defensible.",
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
