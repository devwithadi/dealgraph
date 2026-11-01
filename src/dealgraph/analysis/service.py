"""Evidence-only scoring with an optional OpenAI narrative pass."""

from __future__ import annotations

import re

import httpx

from dealgraph.analysis.providers import bedrock_narrative, openai_narrative
from dealgraph.analysis.scoring import (
    THESIS,
    build_dimensions,
    calculate_score,
    evidence_confidence,
    recommendation_for,
)
from dealgraph.domain.enums import AIProvider, AnalysisMode
from dealgraph.domain.models import Analysis, Candidate, Evidence, Financials

def _fallback(candidate: Candidate, evidence: list[Evidence]) -> dict:
    has_hn = any(item.source_type == "hacker_news" for item in evidence)
    return {
        "summary": f"{candidate.name} addresses {candidate.one_liner.lower()}. Public evidence is {'supported by an HN signal' if has_hn else 'limited to first-party and directory claims'}.",
        "team": f"YC reports a team size of {candidate.team_size}." if candidate.team_size is not None else "Team background is Unknown.",
        "product": candidate.description or candidate.one_liner,
        "market": candidate.industry or "Market category is Unknown.",
        "why_now": (
            "Recent launch, active hiring, and public technical-community attention create a timely signal."
            if has_hn and candidate.is_hiring
            else "The timing case is not yet supported by enough public evidence."
        ),
        "risks": [
            "Revenue, burn, runway, and retention are Unknown.",
            "First-party product claims require customer validation.",
        ],
        "open_questions": [
            "What measurable customer ROI and retention can the founders demonstrate?",
            "Which distribution channel can scale without founder-led sales?",
        ],
        "changes_mind": [
            "Verified usage, retention, or revenue evidence.",
            "Reference calls confirming fast deployment and durable ROI.",
            "Evidence that integrations or proprietary data improve the moat over time.",
        ],
        "analysis_mode": AnalysisMode.DETERMINISTIC_FALLBACK,
    }


def _financials(evidence: list[Evidence]) -> Financials:
    pricing = revenue = funding = None
    cited: list[str] = []
    for item in evidence:
        text = f"{item.claim} {item.excerpt}"
        price_match = re.search(r"\$\s?[\d,.]+\s*(?:/|per)\s*(?:month|year)", text, re.I)
        revenue_match = re.search(r"(?:ARR|annual recurring revenue)[^$]{0,30}(\$\s?[\d,.]+\s*[kmb]?)", text, re.I)
        funding_match = re.search(r"(?:raised|funding)[^$]{0,30}(\$\s?[\d,.]+\s*[kmb]?)", text, re.I)
        if price_match and not pricing:
            pricing = price_match.group(0)
            cited.append(item.id)
        if revenue_match and not revenue:
            revenue = revenue_match.group(1)
            cited.append(item.id)
        if funding_match and not funding:
            funding = funding_match.group(1)
            cited.append(item.id)
    return Financials(
        revenue=revenue,
        burn=None,
        runway=None,
        funding=funding,
        pricing=pricing,
        evidence_ids=list(dict.fromkeys(cited)),
    )


def analyze(
    candidate: Candidate,
    evidence: list[Evidence],
    client: httpx.Client,
    *,
    provider: AIProvider = AIProvider.BEDROCK,
    bedrock_client=None,
) -> Analysis:
    dimensions = build_dimensions(candidate, evidence)
    score = calculate_score(dimensions)
    confidence = evidence_confidence(evidence)
    narrative = None
    if provider == AIProvider.BEDROCK:
        narrative = bedrock_narrative(candidate, evidence, bedrock_client)
    elif provider == AIProvider.OPENAI:
        narrative = openai_narrative(candidate, evidence, client)
    narrative = narrative or _fallback(candidate, evidence)
    return Analysis(
        company=candidate.name,
        thesis=THESIS,
        dimensions=dimensions,
        financials=_financials(evidence),
        score=score,
        confidence=confidence,
        recommendation=recommendation_for(score, confidence),
        **narrative,
    )
