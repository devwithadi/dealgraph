from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.core.errors import AppError
from app.domain.models import Candidate
from app.sourcing.discovery import (
    deduplicate_and_merge_candidates,
    fetch_hn_candidates,
    make_candidate_slug,
    normalize_domain,
    parse_url_seed_candidates,
    search_agent_reach_candidates,
)
from app.sourcing.registry import YC_URL, source_enabled

LOGGER = logging.getLogger("dealgraph.sourcing.candidates")


def _batch_name(batch: str | None) -> str:
    value = (batch or "").strip().lower()
    match = re.fullmatch(r"([ws])\s*(\d{2})", value)
    if match:
        return f"{'winter' if match.group(1) == 'w' else 'summer'} 20{match.group(2)}"
    return value


def lookback_days_from_env() -> int:
    raw = os.getenv("DEALGRAPH_LOOKBACK_DAYS", "30")
    try:
        days = int(raw)
    except ValueError as error:
        raise AppError("DEALGRAPH_LOOKBACK_DAYS must be an integer from 1 to 3650", exit_code=2) from error
    if not 1 <= days <= 3650:
        raise AppError("DEALGRAPH_LOOKBACK_DAYS must be an integer from 1 to 3650", exit_code=2)
    return days


def _candidate(record: dict) -> Candidate:
    launched = record.get("launched_at")
    raw_slug = str(record.get("slug") or record.get("id") or record.get("name") or "startup")
    slug = make_candidate_slug(raw_slug)
    website = str(record.get("website") or "")
    return Candidate(
        slug=slug,
        name=str(record["name"]),
        website=website,
        one_liner=str(record.get("one_liner") or ""),
        description=str(record.get("long_description") or record.get("description") or ""),
        batch=str(record.get("batch") or ""),
        industry=str(record.get("subindustry") or record.get("industry") or ""),
        tags=[str(tag) for tag in record.get("tags") or []],
        team_size=record.get("team_size"),
        launched_at=datetime.fromtimestamp(int(launched), timezone.utc) if launched else None,
        is_hiring=bool(record.get("isHiring") or record.get("is_hiring")),
        source_url=str(record.get("url") or record.get("source_url") or YC_URL),
    )


def select_candidates(
    records: Iterable[dict],
    batch: str | None,
    lookback_days: int,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[Candidate]:
    """Filter and select active candidate startups from structured records within lookback window."""
    if lookback_days < 1:
        raise ValueError("lookback_days must be positive")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    expected_batch = _batch_name(batch)
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=lookback_days)
    selected: list[Candidate] = []
    seen: set[str] = set()
    for record in records:
        if str(record.get("status", "Active")).lower() != "active":
            continue
        candidate = _candidate(record)
        if expected_batch and candidate.batch.lower() != expected_batch:
            continue
        if candidate.launched_at is None or candidate.launched_at < cutoff:
            continue
        domain = normalize_domain(candidate.website) or candidate.slug
        if domain in seen:
            continue
        seen.add(domain)
        selected.append(candidate)
    selected.sort(key=lambda candidate: candidate.launched_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return selected[:limit]


def load_candidates(
    source_file: Path,
    batch: str | None,
    lookback_days: int,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[Candidate]:
    """Load candidates from a JSON file (records or URL list) or plain text seed file."""
    content = source_file.read_text(encoding="utf-8")
    try:
        data = json.loads(content)
        if isinstance(data, list):
            if data and isinstance(data[0], str):
                candidates = parse_url_seed_candidates(data)
                return deduplicate_and_merge_candidates(candidates, limit=limit)
            return select_candidates(data, batch, lookback_days, now=now, limit=limit)
        if isinstance(data, dict):
            if "candidates" in data and isinstance(data["candidates"], list):
                return select_candidates(data["candidates"], batch, lookback_days, now=now, limit=limit)
            if "urls" in data and isinstance(data["urls"], list):
                candidates = parse_url_seed_candidates(data["urls"])
                return deduplicate_and_merge_candidates(candidates, limit=limit)
            return select_candidates([data], batch, lookback_days, now=now, limit=limit)
    except json.JSONDecodeError:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        candidates = parse_url_seed_candidates(lines)
        return deduplicate_and_merge_candidates(candidates, limit=limit)

    return []


def discover_candidates(
    topic: str,
    batch: str | None = None,
    lookback_days: int = 30,
    *,
    client: httpx.Client | None = None,
    yc_records: Iterable[dict] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[Candidate]:
    """Discover candidate startups across multiple sources: YC Directory, Hacker News, Product Hunt, and Agent Reach."""
    all_candidates: list[Candidate] = []

    # Source 1: YC Directory
    if yc_records is not None:
        try:
            yc_cands = select_candidates(yc_records, batch, lookback_days, now=now)
            all_candidates.extend(yc_cands)
            LOGGER.info("added %d candidates from YC Directory", len(yc_cands))
        except Exception as error:
            LOGGER.warning("failed to select YC candidates error=%s", error)

    # Source 2: Hacker News (Show HN), when explicitly enabled.
    if source_enabled("hacker_news"):
        try:
            hn_cands = fetch_hn_candidates(topic, client=client, limit=15)
            all_candidates.extend(hn_cands)
        except Exception as error:
            LOGGER.warning("failed to fetch HN candidates error=%s", error)

    # Source 3: Agent Reach / Exa Multi-Source Discovery (Product Hunt, TechCrunch, GitHub)
    if source_enabled("agent_reach"):
        try:
            reach_cands = search_agent_reach_candidates(topic, runner=runner, limit=15)
            all_candidates.extend(reach_cands)
        except Exception as error:
            LOGGER.warning("failed to search Agent Reach candidates error=%s", error)

    deduped = deduplicate_and_merge_candidates(all_candidates, limit=limit)
    LOGGER.info("discovered total %d unique candidates across sources for topic=%r", len(deduped), topic)
    return deduped
