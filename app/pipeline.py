"""Replayable sourcing -> evidence -> analysis -> memo pipeline."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

from app.analysis import analyze
from app.errors import AppError
from app.logging import bind_request_id, request_headers
from app.memo import render_memo
from app.models import RunSummary
from app.sources import (
    HN_URL,
    YC_URL,
    SafeFetcher,
    SourcePolicyError,
    filter_candidates,
    hn_evidence,
    load_candidates,
    website_evidence,
    yc_evidence,
)

LOGGER = logging.getLogger("dealgraph.pipeline")


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


class Pipeline:
    def __init__(
        self,
        client: httpx.Client | None = None,
        resolver: Callable[[str], list[str]] | None = None,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(10, connect=5),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=5),
            transport=httpx.HTTPTransport(retries=2),
        )
        self.resolver = resolver

    def run(
        self,
        *,
        topic: str,
        batch: str | None,
        limit: int,
        output: Path,
        source_file: Path | None = None,
        offline: bool = False,
        request_id: str | None = None,
    ) -> RunSummary:
        request_id = bind_request_id(request_id)
        LOGGER.info("run started limit=%d offline=%s", limit, offline)
        if not topic.strip():
            raise AppError("topic cannot be empty", exit_code=2)
        output = output.resolve()
        for name in ("evidence", "analyses", "memos"):
            (output / name).mkdir(parents=True, exist_ok=True)
        if source_file:
            try:
                candidates = load_candidates(source_file, topic, batch, limit)
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise AppError("Unable to load the candidate source file", exit_code=3) from error
            source = str(source_file)
        else:
            try:
                response = self.client.get(YC_URL, headers=request_headers(), timeout=20)
                response.raise_for_status()
                candidates = filter_candidates(response.json(), topic, batch, limit)
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                raise AppError("Unable to load the YC candidate feed", exit_code=3) from error
            source = YC_URL
        _write_json(output / "input.json", {"topic": topic, "batch": batch, "limit": limit, "source": source})
        _write_json(output / "candidates.json", [item.model_dump(mode="json") for item in candidates])

        succeeded = 0
        gaps: list[dict[str, str]] = []
        modes: set[str] = set()
        fetcher = SafeFetcher(self.client, self.resolver) if self.resolver else SafeFetcher(self.client)
        for candidate in candidates:
            try:
                evidence = yc_evidence(candidate)
                if not offline:
                    try:
                        evidence += website_evidence(candidate, fetcher, len(evidence) + 1)
                    except (httpx.HTTPError, SourcePolicyError, OSError) as error:
                        LOGGER.warning("candidate enrichment failed stage=website candidate=%r", candidate.slug)
                        gaps.append({"candidate": candidate.slug, "stage": "website", "error": str(error)})
                    try:
                        evidence += hn_evidence(candidate, self.client, len(evidence) + 1)
                    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                        LOGGER.warning("candidate enrichment failed stage=hacker_news candidate=%r", candidate.slug)
                        gaps.append({"candidate": candidate.slug, "stage": "hacker_news", "error": str(error)})
                result = analyze(candidate, evidence, self.client, allow_openai=not offline)
                modes.add(result.analysis_mode)
                _write_json(output / "evidence" / f"{candidate.slug}.json", [item.model_dump(mode="json") for item in evidence])
                _write_json(output / "analyses" / f"{candidate.slug}.json", result.model_dump(mode="json"))
                (output / "memos" / f"{candidate.slug}.md").write_text(
                    render_memo(candidate, result, evidence), encoding="utf-8"
                )
                succeeded += 1
                LOGGER.info("candidate completed candidate=%r", candidate.slug)
            except Exception as error:
                LOGGER.warning(
                    "candidate failed stage=pipeline candidate=%r", candidate.slug, exc_info=True
                )
                gaps.append({"candidate": candidate.slug, "stage": "pipeline", "error": str(error)})

        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        analysis_mode = "openai" if "openai" in modes else "deterministic_fallback"
        _write_json(
            output / "manifest.json",
            {
                "run_id": run_id,
                "request_id": request_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "topic": topic,
                "batch": batch,
                "candidate_source": source,
                "evidence_sources": [YC_URL, HN_URL, "company public websites"],
                "analysis_mode": analysis_mode,
                "model": os.getenv("OPENAI_MODEL") if analysis_mode == "openai" else None,
                "prompt_version": "analysis-v1",
                "candidates": len(candidates),
                "succeeded": succeeded,
                "failed": len(candidates) - succeeded,
                "evidence_gaps": gaps,
            },
        )
        summary = RunSummary(
            run_id=run_id,
            request_id=request_id,
            output=str(output),
            candidates=len(candidates),
            succeeded=succeeded,
            failed=len(candidates) - succeeded,
        )
        LOGGER.info(
            "run completed candidates=%d succeeded=%d failed=%d",
            summary.candidates,
            summary.succeeded,
            summary.failed,
        )
        return summary
