import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from app.domain.models import Candidate
from app.core.errors import AppError
from app.sourcing.registry import YC_URL


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
    return Candidate(
        slug=str(record.get("slug") or record["id"]),
        name=str(record["name"]),
        website=str(record.get("website") or ""),
        one_liner=str(record.get("one_liner") or ""),
        description=str(record.get("long_description") or ""),
        batch=str(record.get("batch") or ""),
        industry=str(record.get("subindustry") or record.get("industry") or ""),
        tags=[str(tag) for tag in record.get("tags") or []],
        team_size=record.get("team_size"),
        launched_at=datetime.fromtimestamp(int(launched), timezone.utc) if launched else None,
        is_hiring=bool(record.get("isHiring")),
        source_url=str(record.get("url") or YC_URL),
    )


def select_candidates(
    records: Iterable[dict],
    batch: str | None,
    lookback_days: int,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[Candidate]:
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
        domain = (urlsplit(candidate.website).hostname or candidate.slug).lower()
        if domain in seen:
            continue
        seen.add(domain)
        selected.append(candidate)
    selected.sort(key=lambda candidate: candidate.launched_at, reverse=True)
    return selected[:limit]


def load_candidates(
    source_file: Path,
    batch: str | None,
    lookback_days: int,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[Candidate]:
    return select_candidates(
        json.loads(source_file.read_text()),
        batch,
        lookback_days,
        now=now,
        limit=limit,
    )
