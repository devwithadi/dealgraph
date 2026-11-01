from __future__ import annotations

import re
from datetime import date

import httpx

from app.analysis.providers import model_for, model_json, screening_model_for
from app.analysis.scoring import THESIS, validate_citations
from app.domain.enums import AIProvider, AnalysisMode
from app.domain.models import Analysis, Candidate, Evidence, Financials, ScreeningDecision
from app.prompts.screening import build_screening_prompt
from app.prompts.synthesis import build_synthesis_prompt
from app.sourcing.registry import financial_source_priority


_AMOUNT = r"\$\s?[\d,.]+(?:\s?[kmb])?"
_FINANCIAL_PATTERNS = {
    "revenue": (
        rf"(?:ARR|MRR|annual recurring revenue|monthly recurring revenue|revenue)\s*(?:was|is|of|reached|:)\s*({_AMOUNT})",
        rf"({_AMOUNT})\s*(?:ARR|MRR|annual recurring revenue|monthly recurring revenue|revenue)",
    ),
    "burn": (rf"(?:monthly\s+)?burn(?:\s+rate)?\s*(?:was|is|of|:)\s*({_AMOUNT})",),
    "runway": (
        r"runway\s*(?:was|is|of|:)\s*(\d+(?:\.\d+)?\s*(?:months?|years?))",
        r"(\d+(?:\.\d+)?\s*(?:months?|years?))\s+(?:of\s+)?runway",
    ),
    "funding": (rf"(?:raised|funding|financing)\s*(?:was|is|of|:)?\s*({_AMOUNT})",),
    "pricing": (rf"({_AMOUNT}\s*(?:/|per)\s*(?:month|year))",),
}
def _financials(evidence: list[Evidence]) -> Financials:
    priority = financial_source_priority()
    ranked = sorted(
        (item for item in evidence if item.source_type in priority),
        key=lambda item: priority[item.source_type],
    )
    values: dict[str, str | None] = {field: None for field in _FINANCIAL_PATTERNS}
    cited: list[str] = []
    for field, patterns in _FINANCIAL_PATTERNS.items():
        for item in ranked:
            text = f"{item.claim} {item.excerpt}"
            match = next((match for pattern in patterns if (match := re.search(pattern, text, re.I))), None)
            if match:
                values[field] = re.sub(r"\s+", " ", match.group(1)).strip()
                cited.append(item.id)
                break
    return Financials(
        revenue=values["revenue"],
        burn=values["burn"],
        runway=values["runway"],
        funding=values["funding"],
        pricing=values["pricing"],
        evidence_ids=list(dict.fromkeys(cited)),
    )


def screen_candidates(
    candidates: list[Candidate],
    topic: str,
    client: httpx.Client,
    *,
    provider: AIProvider,
    bedrock_client=None,
) -> list[ScreeningDecision]:
    if not candidates:
        return []
    payload = model_json(
        build_screening_prompt(candidates, topic),
        provider=provider,
        model=screening_model_for(provider) or "",
        max_tokens=max(400, len(candidates) * 100),
        stage="screening",
        client=client,
        bedrock_client=bedrock_client,
    )
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, list):
        raise ValueError("screening response must contain a decisions array")
    decisions = [ScreeningDecision.model_validate(item) for item in raw_decisions]
    expected = {candidate.slug for candidate in candidates}
    returned = [decision.slug for decision in decisions]
    if len(returned) != len(set(returned)) or set(returned) != expected:
        raise ValueError("screening response must contain each candidate slug exactly once")
    by_slug = {decision.slug: decision for decision in decisions}
    return [by_slug[candidate.slug] for candidate in candidates]


def _synthesis_prompt(candidate: Candidate, evidence: list[Evidence]) -> str:
    return build_synthesis_prompt(
        {
            "company_name": candidate.name,
            "sector": candidate.industry or "Not disclosed",
            "stage": candidate.batch or "Not disclosed",
            "requested_valuation": "Not disclosed",
            "data_room": "Not disclosed",
            "external_evidence": [item.model_dump(mode="json") for item in evidence],
            "analysis_date": date.today().isoformat(),
            "dealgraph_thesis": THESIS,
        }
    )


def _validate_narrative_citations(analysis: Analysis, citations: list[str]) -> None:
    """Require every factual narrative field to carry an inline evidence ID."""
    factual_text = {
        "summary": [analysis.summary],
        "team": [analysis.team],
        "product": [analysis.product],
        "market": [analysis.market],
        "why_now": [analysis.why_now],
        "risks": analysis.risks,
    }
    missing = [
        field
        for field, values in factual_text.items()
        if any(
            value.strip().lower() not in {"unknown", "not disclosed", "n/a"}
            and not any(f"[{evidence_id}]" in value for evidence_id in citations)
            for value in values
        )
    ]
    if missing:
        raise ValueError(f"synthesis fields missing inline citations: {', '.join(missing)}")


def synthesize(
    candidate: Candidate,
    evidence: list[Evidence],
    client: httpx.Client,
    *,
    provider: AIProvider = AIProvider.BEDROCK,
    bedrock_client=None,
) -> Analysis:
    payload = dict(
        model_json(
            _synthesis_prompt(candidate, evidence),
            provider=provider,
            model=model_for(provider) or "",
            max_tokens=1800,
            stage="synthesis",
            client=client,
            bedrock_client=bedrock_client,
        )
    )
    citations = payload.pop("citations", None)
    if not isinstance(citations, list) or not all(isinstance(item, str) for item in citations):
        raise ValueError("synthesis citations must be an array of evidence IDs")
    validate_citations(citations, evidence)
    mode = AnalysisMode.BEDROCK if provider == AIProvider.BEDROCK else AnalysisMode.OPENAI
    analysis = Analysis.model_validate(
        {
            **payload,
            "company": candidate.name,
            "thesis": THESIS,
            "financials": _financials(evidence),
            "analysis_mode": mode,
        }
    )
    _validate_narrative_citations(analysis, citations)
    return analysis
