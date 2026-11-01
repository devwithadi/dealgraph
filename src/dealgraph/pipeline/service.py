"""Replayable sourcing -> evidence -> analysis -> memo pipeline."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

from dealgraph.analysis.providers import model_for, validate_provider_config
from dealgraph.analysis.service import analyze
from dealgraph.core.errors import AppError
from dealgraph.core.logging import bind_request_id, request_headers
from dealgraph.domain.enums import AIProvider, AnalysisMode
from dealgraph.domain.models import RunSummary
from dealgraph.reporting.memo import render_memo
from dealgraph.sourcing.candidates import filter_candidates, load_candidates
from dealgraph.sourcing.evidence import hn_evidence, website_evidence, yc_evidence
from dealgraph.sourcing.policy import SafeFetcher, SourcePolicyError
from dealgraph.sourcing.registry import HN_URL, YC_URL

LOGGER = logging.getLogger("dealgraph.pipeline")


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _summarize_modes(modes: set[AnalysisMode]) -> AnalysisMode:
    if len(modes) > 1:
        return AnalysisMode.MIXED
    return next(iter(modes), AnalysisMode.DETERMINISTIC_FALLBACK)


class Pipeline:
    def __init__(
        self,
        client: httpx.Client | None = None,
        resolver: Callable[[str], list[str]] | None = None,
        bedrock_client=None,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(10, connect=5),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=5),
            transport=httpx.HTTPTransport(retries=2),
        )
        self.resolver = resolver
        self.bedrock_client = bedrock_client

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
        provider: AIProvider = AIProvider.BEDROCK,
    ) -> RunSummary:
        request_id = bind_request_id(request_id)
        LOGGER.info("run started limit=%d offline=%s", limit, offline)
        if not topic.strip():
            raise AppError("topic cannot be empty", exit_code=2)
        if offline and source_file is None:
            raise AppError("offline mode requires a local source file", exit_code=2)
        effective_provider = AIProvider.DETERMINISTIC if offline else provider
        validate_provider_config(effective_provider)
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
        modes: set[AnalysisMode] = set()
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
                result = analyze(
                    candidate,
                    evidence,
                    self.client,
                    provider=effective_provider,
                    bedrock_client=self.bedrock_client,
                )
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
        analysis_mode = _summarize_modes(modes)
        provider_mode = {
            AIProvider.BEDROCK: AnalysisMode.BEDROCK,
            AIProvider.OPENAI: AnalysisMode.OPENAI,
        }.get(effective_provider)
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
                "provider": effective_provider,
                "analysis_mode": analysis_mode,
                "analysis_modes": sorted(mode.value for mode in modes),
                "model": (
                    model_for(effective_provider)
                    if provider_mode in modes
                    else None
                ),
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
