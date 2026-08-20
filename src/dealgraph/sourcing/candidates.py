"""Candidate loading, normalization, filtering, and ranking."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from dealgraph.domain.models import Candidate
from dealgraph.sourcing.registry import YC_URL


def _batch_name(batch: str | None) -> str:
    value = (batch or "").strip().lower()
    match = re.fullmatch(r"([ws])\s*(\d{2})", value)
    if match:
        return f"{'winter' if match.group(1) == 'w' else 'summer'} 20{match.group(2)}"
    return value


def _topic_tokens(topic: str) -> set[str]:
    stop = {"and", "for", "from", "the", "with"}
    return {
        word.rstrip("s")
        for word in re.findall(r"[a-z0-9]+", topic.lower())
        if word not in stop and (len(word) > 2 or word == "ai")
    }


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


def filter_candidates(
    records: Iterable[dict], topic: str, batch: str | None, limit: int
) -> list[Candidate]:
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    expected_batch, tokens = _batch_name(batch), _topic_tokens(topic)
    ranked: list[tuple[int, Candidate]] = []
    seen: set[str] = set()
    for record in records:
        if str(record.get("status", "Active")).lower() != "active":
            continue
        candidate = _candidate(record)
        if expected_batch and candidate.batch.lower() != expected_batch:
            continue
        domain = (urlsplit(candidate.website).hostname or candidate.slug).lower()
        if domain in seen:
            continue
        haystack = " ".join(
            [candidate.name, candidate.one_liner, candidate.description, *candidate.tags]
        ).lower()
        score = sum(token in haystack for token in tokens)
        if tokens and not score:
            continue
        seen.add(domain)
        ranked.append((score, candidate))
    ranked.sort(
        key=lambda item: (
            item[0],
            item[1].launched_at or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    return [candidate for _, candidate in ranked[:limit]]


def load_candidates(
    source_file: Path, topic: str, batch: str | None, limit: int
) -> list[Candidate]:
    return filter_candidates(json.loads(source_file.read_text()), topic, batch, limit)
