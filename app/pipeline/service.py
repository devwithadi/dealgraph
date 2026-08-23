from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.analysis.providers import (
    create_bedrock_client,
    model_for,
    model_name_for_artifact,
    screening_model_for,
    validate_provider_config,
)
from app.analysis.service import screen_candidates, synthesize
from app.core.errors import AppError
from app.core.logging import bind_request_id, request_headers
from app.domain.enums import AIProvider, AnalysisMode, Recommendation
from app.domain.models import RunSummary, ScreeningDecision
from app.reporting.memo import render_memo
from app.sourcing.candidates import load_candidates, lookback_days_from_env, select_candidates
from app.sourcing.evidence import agent_reach_evidence, yc_evidence
from app.sourcing.registry import YC_URL, enabled_manifest_sources, source_enabled

LOGGER = logging.getLogger("dealgraph.pipeline")
SCREENING_BATCH_SIZE = 20


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _summarize_modes(modes: set[AnalysisMode]) -> AnalysisMode | None:
    if len(modes) > 1:
        return AnalysisMode.MIXED
    return next(iter(modes), None)


def _safe_stage_error(error: Exception, stage: str) -> str:
    if isinstance(error, AppError):
        return str(error)
    return f"Invalid {stage} response" if stage == "screening" else "Finalist processing failed"


class Pipeline:
    def __init__(
        self,
        client: httpx.Client | None = None,
        bedrock_client=None,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(10, connect=5),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=5),
            transport=httpx.HTTPTransport(retries=2),
        )
        self.bedrock_client = bedrock_client

    def run(
        self,
        *,
        topic: str,
        batch: str | None,
        limit: int | None,
        output: Path,
        source_file: Path | None = None,
        offline: bool = False,
        request_id: str | None = None,
        provider: AIProvider = AIProvider.BEDROCK,
        now: datetime | None = None,
    ) -> RunSummary:
        request_id = bind_request_id(request_id)
        LOGGER.info("run started offline=%s", offline)
        if not topic.strip():
            raise AppError("topic cannot be empty", exit_code=2)
        if offline:
            raise AppError("offline raw-data runs are unavailable in the LLM-only pipeline", exit_code=2)
        validate_provider_config(provider)
        lookback_days = lookback_days_from_env()
        effective_now = now or datetime.now(timezone.utc)
        output = output.resolve()
        for name in ("evidence", "analyses", "memos"):
            (output / name).mkdir(parents=True, exist_ok=True)

        if source_file:
            try:
                candidates = load_candidates(
                    source_file,
                    batch,
                    lookback_days,
                    now=effective_now,
                    limit=limit,
                )
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise AppError("Unable to load the candidate source file", exit_code=3) from error
            source = str(source_file)
        else:
            if not source_enabled("yc"):
                raise AppError("YC source is disabled in SOURCE_REGISTRY", exit_code=3)
            try:
                response = self.client.get(YC_URL, headers=request_headers(), timeout=20)
                response.raise_for_status()
                candidates = select_candidates(
                    response.json(),
                    batch,
                    lookback_days,
                    now=effective_now,
                    limit=limit,
                )
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                raise AppError("Unable to load the YC candidate feed", exit_code=3) from error
            source = YC_URL

        cutoff = effective_now - timedelta(days=lookback_days)
        _write_json(
            output / "input.json",
            {
                "topic": topic,
                "batch": batch,
                "lookback_days": lookback_days,
                "cutoff": cutoff.isoformat(),
                "limit": limit,
                "source": source,
            },
        )
        _write_json(output / "candidates.json", [item.model_dump(mode="json") for item in candidates])

        bedrock_client = self.bedrock_client
        if provider == AIProvider.BEDROCK and candidates and bedrock_client is None:
            bedrock_client = create_bedrock_client()

        screenings: list[ScreeningDecision] = []
        gaps: list[dict[str, str]] = []
        failed_slugs: set[str] = set()
        for start in range(0, len(candidates), SCREENING_BATCH_SIZE):
            group = candidates[start : start + SCREENING_BATCH_SIZE]
            try:
                screenings.extend(
                    screen_candidates(
                        group,
                        topic,
                        self.client,
                        provider=provider,
                        bedrock_client=bedrock_client,
                    )
                )
            except Exception as error:
                for candidate in group:
                    failed_slugs.add(candidate.slug)
                    gaps.append(
                        {
                            "candidate": candidate.slug,
                            "stage": "screening",
                            "error": _safe_stage_error(error, "screening"),
                        }
                    )
        _write_json(output / "screenings.json", [item.model_dump(mode="json") for item in screenings])

        candidate_by_slug = {candidate.slug: candidate for candidate in candidates}
        finalists = [candidate_by_slug[item.slug] for item in screenings if item.advance]
        succeeded = 0
        modes: set[AnalysisMode] = set()
        shortlist: list[dict[str, object]] = []
        for candidate in finalists:
            try:
                evidence = yc_evidence(candidate)
                evidence += agent_reach_evidence(candidate, topic, len(evidence) + 1)
                result = synthesize(
                    candidate,
                    evidence,
                    self.client,
                    provider=provider,
                    bedrock_client=bedrock_client,
                )
                modes.add(result.analysis_mode)
                _write_json(
                    output / "evidence" / f"{candidate.slug}.json",
                    [item.model_dump(mode="json") for item in evidence],
                )
                _write_json(output / "analyses" / f"{candidate.slug}.json", result.model_dump(mode="json"))
                (output / "memos" / f"{candidate.slug}.md").write_text(
                    render_memo(candidate, result, evidence), encoding="utf-8"
                )
                if result.recommendation != Recommendation.PASS:
                    shortlist.append(
                        {
                            "slug": candidate.slug,
                            "score": result.score,
                            "confidence": result.confidence,
                            "recommendation": result.recommendation,
                        }
                    )
                succeeded += 1
                LOGGER.info("candidate completed candidate=%r", candidate.slug)
            except Exception as error:
                failed_slugs.add(candidate.slug)
                gaps.append(
                    {
                        "candidate": candidate.slug,
                        "stage": "finalist",
                        "error": _safe_stage_error(error, "finalist"),
                    }
                )
                LOGGER.warning("candidate failed stage=finalist candidate=%r", candidate.slug)
        _write_json(output / "shortlist.json", shortlist)

        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        manifest = {
            "run_id": run_id,
            "request_id": request_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "topic": topic,
            "batch": batch,
            "lookback_days": lookback_days,
            "cutoff": cutoff.isoformat(),
            "candidate_source": source,
            "evidence_sources": enabled_manifest_sources(["yc", "agent_reach"]),
            "provider": provider,
            "analysis_mode": _summarize_modes(modes),
            "screening_model": model_name_for_artifact(screening_model_for(provider)),
            "synthesis_model": model_name_for_artifact(model_for(provider)),
            "screening_prompt_version": "screening-v5",
            "synthesis_prompt_version": "synthesis-v4",
            "candidates": len(candidates),
            "screened": len(screenings),
            "finalists": len(finalists),
            "selected": len(shortlist),
            "succeeded": succeeded,
            "failed": len(failed_slugs),
            "evidence_gaps": gaps,
        }
        _write_json(output / "manifest.json", manifest)
        summary = RunSummary(
            run_id=run_id,
            request_id=request_id,
            output=str(output),
            candidates=len(candidates),
            screened=len(screenings),
            finalists=len(finalists),
            selected=len(shortlist),
            succeeded=succeeded,
            failed=len(failed_slugs),
        )
        LOGGER.info(
            "run completed candidates=%d screened=%d finalists=%d succeeded=%d failed=%d",
            summary.candidates,
            summary.screened,
            summary.finalists,
            summary.succeeded,
            summary.failed,
        )
        return summary
