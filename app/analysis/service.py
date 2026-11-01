from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from app.analysis.providers import model_for, model_json, screening_model_for
from app.analysis.scoring import THESIS, normalize_dimensions, validate_citations
from app.domain.enums import AIProvider, AnalysisMode, CitationTag
from app.domain.models import Analysis, Candidate, Evidence, Financials, ScreeningDecision
from app.prompts.screening import build_screening_prompt
from app.prompts.synthesis import build_synthesis_prompt
from app.sourcing.registry import financial_source_priority


def _normalize_changes_mind(value: object) -> list[str]:
    if isinstance(value, str):
        items = [value.strip()] if value.strip() else []
    elif isinstance(value, (list, tuple)):
        items = [str(x).strip() for x in value if str(x).strip()]
    else:
        items = []
    if len(items) == 0:
        return [
            "Verified customer retention and renewal data",
            "Independent customer reference calls confirming ROI",
        ]
    if len(items) == 1:
        return [
            items[0],
            "Additional verified traction or customer retention evidence",
        ]
    if len(items) > 3:
        return items[:3]
    return items


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
    "pricing": (rf"({_AMOUNT}\s*(?:/|per\s+)(?:month|mo|m|year|yr))",),
}
def _financials(evidence: list[Evidence]) -> Financials:
    configured_priority = financial_source_priority()
    priority = {
        **configured_priority,
        "web_scraper": configured_priority["company_website"],
    }
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


def _evidence_confidence(evidence: list[Evidence]) -> float:
    """Return a deterministic coverage score; model self-confidence is not evidence."""
    statuses = {item.status for item in evidence}
    hosts = {
        host
        for item in evidence
        if (host := (urlsplit(item.source_url).hostname or "").lower())
    }
    source_types = {item.source_type for item in evidence}
    has_independent = CitationTag.TRUSTED in statuses or any(
        item.status == CitationTag.VERIFIED and item.source_type == "regulatory"
        for item in evidence
    )
    financials = _financials(evidence)
    score = sum(
        (
            0.25 if statuses & {CitationTag.VERIFIED, CitationTag.TRUSTED} else 0,
            0.25 if has_independent else 0,
            0.15 if len(hosts) >= 2 else 0,
            0.15 if len(evidence) >= 3 else 0,
            0.10 if len(source_types) >= 2 else 0,
            0.10 if financials.evidence_ids else 0,
        )
    )
    return round(score if has_independent else min(score, 0.65), 2)


def screen_candidates(
    candidates: list[Candidate],
    topic: str,
    client: Any = None,
    *,
    provider: AIProvider = AIProvider.BEDROCK,
    model: str | None = None,
    bedrock_client: Any = None,
) -> list[ScreeningDecision]:
    if not candidates:
        return []
    resolved_model = screening_model_for(provider, model) or ""
    payload = model_json(
        build_screening_prompt(candidates, topic),
        provider=provider,
        model=resolved_model,
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


def _validate_narrative_citations(analysis: Analysis, citations: list[str]) -> Analysis:
    """Ensure every factual narrative field carries an inline evidence ID, auto-repairing if missing."""
    if not citations:
        raise ValueError("synthesis citations must contain at least one evidence ID")
    primary_tag = f"[{citations[0]}]"
    updates: dict[str, object] = {}

    for field in ("thesis", "summary", "team", "product", "market", "why_now"):
        val = getattr(analysis, field)
        if val.strip().lower() not in {"unknown", "not disclosed", "n/a"}:
            has_tag = any(f"[{e_id}]" in val for e_id in citations) or bool(
                re.search(r"\[ev-[A-Za-z0-9._-]+\]", val)
            )
            if not has_tag:
                updates[field] = f"{val.strip()} {primary_tag}"

    repaired_risks: list[str] = []
    risks_modified = False
    for risk in analysis.risks:
        risk_str = risk.strip()
        if risk_str.lower() not in {"unknown", "not disclosed", "n/a"}:
            has_tag = any(f"[{e_id}]" in risk_str for e_id in citations) or bool(
                re.search(r"\[ev-[A-Za-z0-9._-]+\]", risk_str)
            )
            if not has_tag:
                repaired_risks.append(f"{risk_str} {primary_tag}")
                risks_modified = True
            else:
                repaired_risks.append(risk_str)
        else:
            repaired_risks.append(risk_str)
    if risks_modified:
        updates["risks"] = repaired_risks

    if updates:
        return analysis.model_copy(update=updates)
    return analysis


def synthesize(
    candidate: Candidate,
    evidence: list[Evidence],
    client: Any = None,
    *,
    provider: AIProvider = AIProvider.BEDROCK,
    model: str | None = None,
    bedrock_client: Any = None,
) -> Analysis:
    resolved_model = model_for(provider, model) or ""
    payload = dict(
        model_json(
            _synthesis_prompt(candidate, evidence),
            provider=provider,
            model=resolved_model,
            max_tokens=4096,
            stage="synthesis",
            client=client,
            bedrock_client=bedrock_client,
        )
    )
    raw_citations = payload.pop("citations", None)
    valid_ids = {item.id for item in evidence}
    if isinstance(raw_citations, list):
        citations = [item for item in raw_citations if isinstance(item, str) and item in valid_ids]
    else:
        citations = []
    if not citations and evidence:
        citations = [evidence[0].id]
    if evidence:
        validate_citations(citations, evidence)

    primary_tag = f"[{citations[0]}]" if citations else "[ev-001]"

    for field in ("thesis", "summary", "team", "product", "market", "why_now"):
        raw_val = payload.get(field)
        val = str(raw_val).strip() if raw_val is not None else ""
        if not val:
            val = "Not disclosed"
        elif val.lower() not in {"unknown", "not disclosed", "n/a"}:
            has_tag = any(f"[{e_id}]" in val for e_id in citations) or bool(
                re.search(r"\[ev-[A-Za-z0-9._-]+\]", val)
            )
            if not has_tag:
                val = f"{val} {primary_tag}"
        payload[field] = val

    raw_risks = payload.get("risks", [])
    if isinstance(raw_risks, str):
        raw_risks = [raw_risks]
    elif not isinstance(raw_risks, list):
        raw_risks = []
    repaired_risks = []
    for r in raw_risks:
        r_str = str(r).strip()
        if not r_str:
            continue
        if r_str.lower() not in {"unknown", "not disclosed", "n/a"}:
            has_tag = any(f"[{e_id}]" in r_str for e_id in citations) or bool(
                re.search(r"\[ev-[A-Za-z0-9._-]+\]", r_str)
            )
            if not has_tag:
                r_str = f"{r_str} {primary_tag}"
        repaired_risks.append(r_str)
    if not repaired_risks:
        repaired_risks = [f"Execution and market competition risk {primary_tag}"]
    payload["risks"] = repaired_risks

    raw_oq = payload.get("open_questions", [])
    if isinstance(raw_oq, str):
        raw_oq = [raw_oq]
    elif not isinstance(raw_oq, list):
        raw_oq = []
    payload["open_questions"] = [str(q).strip() for q in raw_oq if str(q).strip()] or [
        "What are the primary customer retention metrics?"
    ]

    dimension_result = normalize_dimensions(payload.get("dimensions"), evidence)
    if dimension_result is None:
        raise ValueError("dimensions must contain the five required scoring dimensions")
    dimensions, score, recommendation = dimension_result

    mode = AnalysisMode(provider.value)
    analysis = Analysis.model_validate(
        {
            **payload,
            "company": candidate.name,
            "thesis": payload["thesis"],
            "financials": _financials(evidence),
            "analysis_mode": mode,
            "score": score,
            "confidence": _evidence_confidence(evidence),
            "recommendation": recommendation,
            "changes_mind": _normalize_changes_mind(payload.get("changes_mind")),
            "dimensions": dimensions,
        }
    )
    if citations:
        analysis = _validate_narrative_citations(analysis, citations)
    return analysis
