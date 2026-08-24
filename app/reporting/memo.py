from __future__ import annotations

import re
from typing import Any

from app.analysis.diligence.evaluator import PILLAR_KEYWORDS
from app.domain.models import Candidate, Evidence


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
