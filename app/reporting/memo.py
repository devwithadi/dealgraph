from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any

from app.analysis.diligence.evaluator import PILLAR_KEYWORDS
from app.analysis.diligence.models import DiligencePillar
from app.domain.enums import CitationTag, Recommendation
from app.domain.models import Analysis, Candidate, Evidence


def _format_badge_decision(recommendation: Recommendation) -> str:
    if recommendation == Recommendation.TAKE_A_MEETING:
        return "🟢 **TAKE A MEETING**"
    if recommendation == Recommendation.WATCH:
        return "🟡 **WATCH**"
    return "🔴 **PASS**"


def _format_tag_badge(tag: CitationTag) -> str:
    if tag == CitationTag.VERIFIED:
        return "`VERIFIED`"
    if tag == CitationTag.TRUSTED:
        return "`TRUSTED`"
    return "`CLAIMED`"


def _format_source_category(item: Evidence, candidate: Candidate | None = None) -> str:
    """Map technical source type and trust tier to an investor-friendly category."""
    st = (item.source_type or "").lower()
    tt = (item.trust_tier or "").lower()
    url = (item.source_url or "").lower()

    # Check if URL matches candidate official website domain
    if candidate and candidate.website:
        cand_domain = re.sub(r"^https?://(www\.)?", "", candidate.website.lower()).split("/")[0].strip()
        if cand_domain and cand_domain in url:
            return "Company Website"

    if "yc" in st or "registry" in tt or "directory" in tt or "ycombinator" in url or "sec.gov" in url:
        return "Official Registry"
    if st in {"news", "press", "media"} or any(m in url for m in ["techcrunch", "bloomberg", "reuters", "forbes", "runtimewire", "venturebeat"]):
        return "Press / Media"
    if st in {"web_scraper", "landing_page", "company_website", "self_reported"} or tt in {"self_reported", "first_party_self_reported"}:
        return "Company Website"
    if st in {"deep_diligence", "deep_diligence_search", "agent_reach", "web"} or tt in {"multi_hop_web", "open_web"}:
        return "Web Research"
    return "Web Research"


def _build_evidence_map(evidence: list[Evidence]) -> dict[str, tuple[int, Evidence]]:
    mapping: dict[str, tuple[int, Evidence]] = {}
    for idx, ev in enumerate(evidence, start=1):
        mapping[ev.id.lower()] = (idx, ev)
        # Also map without leading zeros if any e.g. ev-1 -> ev-001
        m = re.match(r"^ev-0*(\d+)$", ev.id.lower())
        if m:
            num = m.group(1)
            mapping[f"ev-{num}"] = (idx, ev)
            mapping[f"ev-{int(num):03d}"] = (idx, ev)
            mapping[num] = (idx, ev)
        mapping[str(idx)] = (idx, ev)
        mapping[f"ev-{idx}"] = (idx, ev)
        mapping[f"ev-{idx:03d}"] = (idx, ev)
    return mapping


def _resolve_evidence_entry(key: str, evidence_map: dict[str, Any]) -> tuple[int, Evidence] | None:
    norm_key = key.lower().strip()
    entry = evidence_map.get(norm_key)
    if entry is None:
        m = re.search(r"\d+", norm_key)
        if m:
            num_str = str(int(m.group(0)))
            entry = (
                evidence_map.get(num_str)
                or evidence_map.get(f"ev-{num_str}")
                or evidence_map.get(f"ev-{int(num_str):03d}")
            )
    if entry is None:
        return None
    if isinstance(entry, tuple) and len(entry) == 2 and isinstance(entry[0], int) and isinstance(entry[1], Evidence):
        return entry
    if isinstance(entry, Evidence):
        m = re.search(r"\d+", entry.id)
        idx = int(m.group(0)) if m else 1
        return (idx, entry)
    return None


def transform_citations(text: str, evidence_map: dict[str, Any]) -> str:
    """Transform raw [ev-XXX] or composite citations into compact, clickable markdown citation links [[1] ↗](url)."""
    if not text:
        return ""

    def replace_bracket_citations(match: re.Match) -> str:
        inner = match.group(1)
        ev_ids = re.findall(r"ev-\d+", inner, flags=re.IGNORECASE)
        if not ev_ids:
            return match.group(0)

        seen: set[str] = set()
        unique_ev_ids: list[str] = []
        for ev_id in ev_ids:
            norm = ev_id.lower()
            if norm not in seen:
                seen.add(norm)
                unique_ev_ids.append(ev_id)

        rendered: list[str] = []
        for ev_id in unique_ev_ids:
            resolved = _resolve_evidence_entry(ev_id, evidence_map)
            if resolved is not None:
                idx, ev = resolved
                url = ev.source_url if ev.source_url and ev.source_url.startswith(("http://", "https://")) else f"#source-{idx}"
                rendered.append(f"[[{idx}] ↗]({url})")
            else:
                rendered.append(f"[[{ev_id.upper()}] ↗](#auditable-sources)")
        return " ".join(rendered)

    def replace_single_citation(match: re.Match) -> str:
        ev_id = match.group(1)
        resolved = _resolve_evidence_entry(ev_id, evidence_map)
        if resolved is not None:
            idx, ev = resolved
            url = ev.source_url if ev.source_url and ev.source_url.startswith(("http://", "https://")) else f"#source-{idx}"
            return f"[[{idx}] ↗]({url})"
        return f"[[{ev_id.upper()}] ↗](#auditable-sources)"

    # Pass 1: Bracketed citations like [ev-001, ev-003, ev-005] or [ev-001]
    res = re.sub(r"\[\s*([^\]]*\bev-\d+[^\]]*)\s*\]", replace_bracket_citations, text, flags=re.IGNORECASE)
    # Pass 2: Parenthesized citations like (ev-001, ev-003) or (ev-001)
    res = re.sub(r"\(\s*([^)]*\bev-\d+[^)]*)\s*\)", replace_bracket_citations, res, flags=re.IGNORECASE)
    # Pass 3: Standalone unbracketed ev-XXX citations
    res = re.sub(r"(?<![\[\w-])(ev-\d+)(?![\]\w-])", replace_single_citation, res, flags=re.IGNORECASE)
    return res


def _extract_pillar_summary(text: str, max_chars: int = 140) -> str:
    # Strip any citations (markdown links or raw [ev-XXX]) so scorecard table is clean and un-truncated
    cleaned = re.sub(r"\[\[[^\]]+\]\s*↗\]\([^)]+\)", "", text)
    cleaned = re.sub(r"\[\s*ev-\d+[^\]]*\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rsplit(" ", 1)[0] + "..."


def render_memo(candidate: Candidate, analysis: Analysis, evidence: list[Evidence]) -> str:
    """Render a publication-grade Tier-1 VC Investment Committee Memo."""
    ev_map = _build_evidence_map(evidence)

    # Decision, score, confidence, and stage/batch badges (no internal provider jargon)
    decision_badge = _format_badge_decision(analysis.recommendation)
    score_badge = f"`Score: {analysis.score:.1f}/100`"
    confidence_badge = f"`Confidence: {analysis.confidence:.0%}`"
    batch_val = candidate.batch.strip() if candidate.batch else ""
    stage_badge = f"`Batch: {batch_val}`" if batch_val and batch_val.lower() != "general" else "`Stage: Pre-Seed / Seed`"

    # Citation-transformed narrative fields
    thesis_tx = transform_citations(analysis.thesis, ev_map)
    summary_tx = transform_citations(analysis.summary, ev_map)
    team_tx = transform_citations(analysis.team, ev_map)
    product_tx = transform_citations(analysis.product, ev_map)
    market_tx = transform_citations(analysis.market, ev_map)
    why_now_tx = transform_citations(analysis.why_now, ev_map)

    risks_tx = [transform_citations(r, ev_map) for r in analysis.risks]
    questions_tx = [transform_citations(q, ev_map) for q in analysis.open_questions]
    changes_tx = [transform_citations(c, ev_map) for c in analysis.changes_mind]

    # Crown jewel & inverse case callouts
    crown_jewel_text = analysis.thesis if analysis.thesis else f"Defensible positioning in {candidate.industry or 'market'} with proprietary capability."
    crown_jewel_tx = transform_citations(crown_jewel_text, ev_map)

    inverse_case_text = analysis.risks[0] if analysis.risks else "High execution risk and market crowding."
    inverse_case_tx = transform_citations(inverse_case_text, ev_map)

    # Financials lines
    financial_items = [
        ("Revenue / ARR", analysis.financials.revenue or "Undisclosed / Pre-revenue"),
        ("Burn Rate", analysis.financials.burn or "Undisclosed"),
        ("Runway", analysis.financials.runway or "Undisclosed"),
        ("Total Funding", analysis.financials.funding or "Undisclosed"),
        ("Pricing Model", analysis.financials.pricing or "Undisclosed"),
    ]
    financials_md = "\n".join(f"- **{label}:** {transform_citations(val, ev_map)}" for label, val in financial_items)

    # Metadata table
    website_link = f"[{candidate.website}]({candidate.website})" if candidate.website else "N/A"
    batch_str = candidate.batch.strip() or "General"
    industry_str = candidate.industry.strip() or "Technology"
    team_size_str = str(candidate.team_size) if candidate.team_size is not None else "Undisclosed"
    hiring_str = "🟢 Actively Hiring" if candidate.is_hiring else "Not Specified"
    today_str = datetime.now(timezone.utc).strftime("%B %d, %Y")

    # 4-Pillar Scorecard
    scorecard_rows = [
        (
            "Commercial / TAM",
            _extract_pillar_summary(transform_citations(analysis.market or candidate.one_liner, ev_map)),
            sum(1 for e in evidence if any(k in f"{e.claim} {e.excerpt}".lower() for k in PILLAR_KEYWORDS[DiligencePillar.COMMERCIAL_TAM.value])),
        ),
        (
            "Financials / Unit Economics",
            _extract_pillar_summary(transform_citations(analysis.financials.pricing or analysis.financials.revenue or "Pre-revenue monetization model", ev_map)),
            sum(1 for e in evidence if any(k in f"{e.claim} {e.excerpt}".lower() for k in PILLAR_KEYWORDS[DiligencePillar.UNIT_ECONOMICS.value])),
        ),
        (
            "Tech / IP Defensibility",
            _extract_pillar_summary(transform_citations(analysis.product or candidate.description, ev_map)),
            sum(1 for e in evidence if any(k in f"{e.claim} {e.excerpt}".lower() for k in PILLAR_KEYWORDS[DiligencePillar.TECH_IP.value])),
        ),
        (
            "Risk / ESG",
            _extract_pillar_summary(transform_citations(analysis.risks[0] if analysis.risks else "Manageable platform risk", ev_map)),
            sum(1 for e in evidence if any(k in f"{e.claim} {e.excerpt}".lower() for k in PILLAR_KEYWORDS[DiligencePillar.RISK_ESG.value])),
        ),
    ]

    scorecard_table_md = "\n".join(
        f"| **{pillar}** | {summary} | {ev_count} item(s) |"
        for pillar, summary, ev_count in scorecard_rows
    )

    # Investor-facing Sources Table
    sources_rows: list[str] = []
    for idx, item in enumerate(evidence, start=1):
        tag_str = _format_tag_badge(item.status)
        raw_title = item.source_title.strip() or item.claim.strip() or f"Source {idx}"
        clean_title = raw_title.rstrip(" ↗").strip()
        url_link = f"[{clean_title} ↗]({item.source_url})" if item.source_url and item.source_url.startswith(("http://", "https://")) else clean_title
        category = _format_source_category(item, candidate)
        snippet_clean = re.sub(r"\s+", " ", item.excerpt).strip()
        if len(snippet_clean) > 180:
            snippet_clean = snippet_clean[:177].rsplit(" ", 1)[0] + "..."
        sources_rows.append(
            f"| <a id=\"source-{idx}\"></a>[{idx}] | {tag_str} | {url_link} | {category} | {snippet_clean} |"
        )
    sources_table_md = "\n".join(sources_rows)

    risks_md = "\n".join(f"- {r}" for r in risks_tx)
    questions_md = "\n".join(f"- {q}" for q in questions_tx)
    changes_md = "\n".join(f"- {c}" for c in changes_tx)

    return f"""# [INVESTMENT COMMITTEE MEMO] {candidate.name}

{decision_badge} · {score_badge} · {confidence_badge} · {stage_badge}

---

### Executive Overview
| Property | Specification |
| :--- | :--- |
| **Website** | {website_link} |
| **Batch / Program** | {batch_str} |
| **Sector / Industry** | {industry_str} |
| **Team Size** | {team_size_str} |
| **Hiring Status** | {hiring_str} |
| **Evaluation Date** | {today_str} |

---

### 4-Pillar Diligence Scorecard
| Diligence Pillar | Key Finding / Assessment | Evidence Backing |
| :--- | :--- | :--- |
{scorecard_table_md}

---

> 💎 **CROWN JEWEL ASSET:** {crown_jewel_tx}

> ⚠️ **THE INVERSE CASE (Failure Mode & Tripwires):** {inverse_case_tx}

---

## 1. Executive Summary & Investment Thesis

{summary_tx}

### Investment Thesis
{thesis_tx}

## 2. Team & Founder Capability

{team_tx}

## 3. Product Architecture & TRL

{product_tx}

## 4. Market Dynamics & Why Now

{market_tx}

### Why Now Catalyst
{why_now_tx}

## 5. Financials & Unit Economics

{financials_md}

## 6. Critical Risks & Stress-Testing

### Key Risks & Vulnerabilities
{risks_md}

### Open Diligence Questions
{questions_md}

## 7. Triggers ("What Would Change Our Mind")

{changes_md}

---

<a id="auditable-sources"></a>
## 8. Auditable Sources & References

| # | Trust Tag | Source & Publisher | Category | Key Excerpt |
| :---: | :--- | :--- | :--- | :--- |
{sources_table_md}
"""
