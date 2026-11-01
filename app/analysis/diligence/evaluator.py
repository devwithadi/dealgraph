from __future__ import annotations

import re

from app.analysis.diligence.models import DiligencePillar, InformationGap, SearchQuery
from app.domain.models import Candidate, Evidence

PILLAR_KEYWORDS: dict[str, list[str]] = {
    DiligencePillar.COMMERCIAL_TAM.value: [
        "market",
        "customer",
        "traction",
        "competitor",
        "client",
        "tam",
        "industry",
        "segment",
        "growth",
        "pilot",
        "sales",
        "pipeline",
        "founder",
        "ceo",
        "cto",
        "exit",
        "background",
        "sentiment",
        "review",
    ],
    DiligencePillar.UNIT_ECONOMICS.value: [
        "pricing",
        "revenue",
        "arr",
        "mrr",
        "$",
        "funding",
        "raised",
        "burn",
        "runway",
        "margin",
        "economics",
        "tier",
        "subscription",
        "valuation",
    ],
    DiligencePillar.TECH_IP.value: [
        "tech",
        "architecture",
        "patent",
        "proprietary",
        "model",
        "algorithm",
        "moat",
        "data",
        "infrastructure",
        "api",
        "stack",
        "benchmark",
        "llm",
        "integration",
    ],
    DiligencePillar.RISK_ESG.value: [
        "risk",
        "churn",
        "regulation",
        "compliance",
        "threat",
        "liability",
        "dependency",
        "limitation",
        "vulnerability",
        "challenge",
        "gdpr",
        "soc2",
        "legal",
        "security",
    ],
}


def _find_matching_evidence(pillar: str, evidence: list[Evidence]) -> Evidence | None:
    keywords = PILLAR_KEYWORDS.get(pillar, [])
    for item in evidence:
        text = f"{item.claim} {item.excerpt} {item.source_title}".lower()
        if any(re.search(rf"\b{re.escape(kw)}\b", text) or (kw == "$" and "$" in text) for kw in keywords):
            return item
    return None


def evaluate_evidence_gaps(
    candidate: Candidate,
    evidence: list[Evidence],
    topic: str = "",
) -> list[InformationGap]:
    """Inspect current evidence across 4 pillars to identify gaps."""
    gaps: list[InformationGap] = []

    # 1. Commercial / TAM
    ev_commercial = _find_matching_evidence(DiligencePillar.COMMERCIAL_TAM.value, evidence)
    if ev_commercial is None:
        gaps.append(
            InformationGap(
                pillar=DiligencePillar.COMMERCIAL_TAM.value,
                description=f"Missing independent validation of TAM, customer acquisition, or competitor traction for {candidate.name}.",
                severity="high",
                resolved=False,
                rationale="No verified commercial or customer demand signals found in current evidence.",
            )
        )
    else:
        gaps.append(
            InformationGap(
                pillar=DiligencePillar.COMMERCIAL_TAM.value,
                description=f"Commercial and market demand evidence identified.",
                severity="low",
                resolved=True,
                rationale=f"Found commercial evidence in {ev_commercial.id}.",
                resolved_by_evidence_id=ev_commercial.id,
            )
        )

    # 2. Unit Economics
    ev_econ = _find_matching_evidence(DiligencePillar.UNIT_ECONOMICS.value, evidence)
    if ev_econ is None:
        gaps.append(
            InformationGap(
                pillar=DiligencePillar.UNIT_ECONOMICS.value,
                description=f"No verified pricing structure, revenue milestones, funding rounds, or burn figures for {candidate.name}.",
                severity="high",
                resolved=False,
                rationale="No financial or unit economics data points extracted.",
            )
        )
    else:
        gaps.append(
            InformationGap(
                pillar=DiligencePillar.UNIT_ECONOMICS.value,
                description=f"Financial and unit economics data identified.",
                severity="low",
                resolved=True,
                rationale=f"Found economics evidence in {ev_econ.id}.",
                resolved_by_evidence_id=ev_econ.id,
            )
        )

    # 3. Tech / IP Defensibility
    ev_tech = _find_matching_evidence(DiligencePillar.TECH_IP.value, evidence)
    if ev_tech is None:
        gaps.append(
            InformationGap(
                pillar=DiligencePillar.TECH_IP.value,
                description=f"Lack of technical deep-dive into proprietary architecture, data defensibility, or IP moat for {candidate.name}.",
                severity="medium",
                resolved=False,
                rationale="Current profile lacks technical depth beyond high-level product description.",
            )
        )
    else:
        gaps.append(
            InformationGap(
                pillar=DiligencePillar.TECH_IP.value,
                description=f"Technical architecture and defensibility evidence identified.",
                severity="low",
                resolved=True,
                rationale=f"Found technical evidence in {ev_tech.id}.",
                resolved_by_evidence_id=ev_tech.id,
            )
        )

    # 4. Risk / ESG
    ev_risk = _find_matching_evidence(DiligencePillar.RISK_ESG.value, evidence)
    if ev_risk is None:
        gaps.append(
            InformationGap(
                pillar=DiligencePillar.RISK_ESG.value,
                description=f"Unassessed execution, regulatory compliance, platform dependency, or churn risks for {candidate.name}.",
                severity="medium",
                resolved=False,
                rationale="No critical risk evaluation or regulatory analysis in current corpus.",
            )
        )
    else:
        gaps.append(
            InformationGap(
                pillar=DiligencePillar.RISK_ESG.value,
                description=f"Risk factors and regulatory context identified.",
                severity="low",
                resolved=True,
                rationale=f"Found risk evidence in {ev_risk.id}.",
                resolved_by_evidence_id=ev_risk.id,
            )
        )

    return gaps


def generate_followup_queries(
    candidate: Candidate,
    gaps: list[InformationGap],
    hop: int,
    topic: str = "",
) -> list[SearchQuery]:
    """Generate follow-up search queries targeting unresolved information gaps."""
    unresolved = [gap for gap in gaps if not gap.resolved]
    queries: list[SearchQuery] = []
    name = candidate.name.strip()

    for gap in unresolved:
        if gap.pillar == DiligencePillar.COMMERCIAL_TAM.value:
            queries.append(
                SearchQuery(
                    query=f"{name} customer case study enterprise traction testimonials competitors market share",
                    pillar=gap.pillar,
                    rationale=f"Resolve Commercial/TAM gap: {gap.description}",
                    hop=hop,
                )
            )
        elif gap.pillar == DiligencePillar.UNIT_ECONOMICS.value:
            queries.append(
                SearchQuery(
                    query=f"{name} subscription pricing cost per user ARR funding round Seed Series A valuation",
                    pillar=gap.pillar,
                    rationale=f"Resolve Unit Economics gap: {gap.description}",
                    hop=hop,
                )
            )
        elif gap.pillar == DiligencePillar.TECH_IP.value:
            queries.append(
                SearchQuery(
                    query=f"{name} technical architecture GitHub documentation AI model fine-tuning benchmark",
                    pillar=gap.pillar,
                    rationale=f"Resolve Tech/IP gap: {gap.description}",
                    hop=hop,
                )
            )
        elif gap.pillar == DiligencePillar.RISK_ESG.value:
            queries.append(
                SearchQuery(
                    query=f"{name} security compliance GDPR SOC2 regulatory scrutiny customer churn limitations",
                    pillar=gap.pillar,
                    rationale=f"Resolve Risk/ESG gap: {gap.description}",
                    hop=hop,
                )
            )

    return queries
