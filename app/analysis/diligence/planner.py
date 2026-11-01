from __future__ import annotations

from app.analysis.diligence.models import DiligencePillar, DiligencePlan, SearchQuery
from app.domain.models import Candidate, Evidence


def generate_diligence_plan(
    candidate: Candidate,
    topic: str,
    initial_evidence: list[Evidence] | None = None,
) -> DiligencePlan:
    """Generate a targeted 4-pillar + founder diligence research plan for a candidate."""
    name = candidate.name.strip()
    website = candidate.website.strip()
    industry = candidate.industry.strip() or topic
    one_liner = candidate.one_liner.strip()

    focus_areas = [
        f"Founder technical background & previous exits for {name}",
        f"Commercial / TAM validation & competitor comparisons in {industry}",
        f"Pricing model & unit economics for {name}",
        f"Product tech architecture, proprietary models & integrations for {one_liner}",
        f"Security, compliance & regulatory risks for {name}",
    ]

    queries: list[SearchQuery] = [
        SearchQuery(
            query=f"{name} founder CEO CTO background previous exits technical experience track record",
            pillar=DiligencePillar.COMMERCIAL_TAM.value,
            rationale=f"Investigate founder technical pedigree, prior entrepreneurial exits, and domain credibility for {name}.",
            hop=1,
        ),
        SearchQuery(
            query=f"{name} ({website}) market size target customers competitors customer reviews sentiment commercial traction {topic}",
            pillar=DiligencePillar.COMMERCIAL_TAM.value,
            rationale=f"Validate market demand, competitive positioning, customer sentiment, and segment traction for {name}.",
            hop=1,
        ),
        SearchQuery(
            query=f"{name} pricing model tiers revenue ARR MRR funding valuation burn unit economics gross margins",
            pillar=DiligencePillar.UNIT_ECONOMICS.value,
            rationale=f"Determine pricing structure, monetization model, revenue metrics, and historical financing for {name}.",
            hop=1,
        ),
        SearchQuery(
            query=f"{name} product tech architecture integrations proprietary models data moat IP defensibility benchmarks API",
            pillar=DiligencePillar.TECH_IP.value,
            rationale=f"Assess product technical architecture, proprietary models, integrations, and IP defensibility.",
            hop=1,
        ),
        SearchQuery(
            query=f"{name} security SOC2 ISO compliance regulatory risks GDPR customer churn platform dependencies vulnerabilities",
            pillar=DiligencePillar.RISK_ESG.value,
            rationale=f"Identify regulatory bottlenecks, security posture, compliance, platform dependencies, and execution risks.",
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
