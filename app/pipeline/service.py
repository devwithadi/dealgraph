from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.analysis.diligence import DeepDiligenceAgent
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
from app.domain.models import Analysis, Candidate, Evidence, RunSummary, ScreeningDecision
from app.reporting.memo import render_memo
from app.reporting.pdf import render_pdf_memo
from app.sourcing.candidates import (
    discover_candidates,
    load_candidates,
    lookback_days_from_env,
    select_candidates,
)
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
    msg = str(error).strip()
    if msg:
        return f"{type(error).__name__}: {msg}"
    return f"{stage.capitalize()} failed"


def _emit(
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
    event: str,
    data: dict[str, Any],
) -> None:
    if progress_callback is not None:
        try:
            progress_callback(event, data)
        except Exception:
            pass


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
        screening_model: str | None = None,
        synthesis_model: str | None = None,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
        now: datetime | None = None,
        deep_diligence: bool = False,
        max_hops: int = 2,
    ) -> RunSummary:
        request_id = bind_request_id(request_id)
        LOGGER.info("run started offline=%s deep_diligence=%s", offline, deep_diligence)
        if not topic.strip():
            raise AppError("topic cannot be empty", exit_code=2)
        if offline:
            output_resolved = output.resolve()
            if (
                (output_resolved / "candidates.json").is_file()
                and (output_resolved / "analyses").is_dir()
                and (output_resolved / "evidence").is_dir()
            ):
                return self.replay(
                    output_resolved,
                    progress_callback=progress_callback,
                    request_id=request_id,
                )
            raise AppError("offline raw-data runs are unavailable in the LLM-only pipeline", exit_code=2)
        validate_provider_config(provider, screening_model, synthesis_model)
        resolved_screening_model = screening_model_for(provider, screening_model) or ""
        resolved_synthesis_model = model_for(provider, synthesis_model) or ""
        lookback_days = lookback_days_from_env()
        effective_now = now or datetime.now(timezone.utc)
        cutoff = effective_now - timedelta(days=lookback_days)
        output = output.resolve()
        for name in ("evidence", "analyses", "memos"):
            (output / name).mkdir(parents=True, exist_ok=True)

        _emit(
            progress_callback,
            "header",
            {
                "topic": topic,
                "lookback_days": lookback_days,
                "cutoff": cutoff.isoformat(),
                "provider": provider,
                "screening_model": resolved_screening_model,
                "synthesis_model": resolved_synthesis_model,
                "output": str(output),
                "deep_diligence": deep_diligence,
                "max_hops": max_hops,
            },
        )

        _emit(
            progress_callback,
            "sourcing_start",
            {"source": str(source_file) if source_file else YC_URL},
        )

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
            yc_records = None
            try:
                response = self.client.get(YC_URL, headers=request_headers(), timeout=20)
                response.raise_for_status()
                yc_records = response.json()
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                LOGGER.warning("YC candidate feed error=%s; falling back to multi-source discovery", error)

            candidates = discover_candidates(
                topic=topic,
                batch=batch,
                lookback_days=lookback_days,
                client=self.client,
                yc_records=yc_records,
                now=effective_now,
                limit=limit,
            )
            if not candidates:
                raise AppError("Unable to load candidate startups from sourcing channels", exit_code=3)
            source = YC_URL if (yc_records and not source_enabled("hacker_news") and not source_enabled("agent_reach")) else "Multi-Source (YC Directory, Hacker News, Agent Reach)"

        _emit(
            progress_callback,
            "sourcing_complete",
            {
                "count": len(candidates),
                "lookback_days": lookback_days,
                "source": source,
            },
        )

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
        total_batches = (len(candidates) + SCREENING_BATCH_SIZE - 1) // SCREENING_BATCH_SIZE if candidates else 0
        _emit(
            progress_callback,
            "screening_start",
            {"total": len(candidates), "batch_size": SCREENING_BATCH_SIZE},
        )
        for batch_num, start in enumerate(range(0, len(candidates), SCREENING_BATCH_SIZE), start=1):
            group = candidates[start : start + SCREENING_BATCH_SIZE]
            try:
                group_decisions = screen_candidates(
                    group,
                    topic,
                    self.client,
                    provider=provider,
                    model=resolved_screening_model,
                    bedrock_client=bedrock_client,
                )
                screenings.extend(group_decisions)
                group_candidate_by_slug = {c.slug: c for c in group}
                _emit(
                    progress_callback,
                    "screening_batch",
                    {
                        "batch_number": batch_num,
                        "total_batches": total_batches,
                        "start_index": start + 1,
                        "end_index": min(start + SCREENING_BATCH_SIZE, len(candidates)),
                        "decisions": [
                            {
                                "slug": d.slug,
                                "name": group_candidate_by_slug.get(d.slug, group[0]).name,
                                "fit_score": d.fit_score,
                                "advance": d.advance,
                                "rationale": d.rationale,
                            }
                            for d in group_decisions
                        ],
                    },
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
        _emit(
            progress_callback,
            "screening_complete",
            {"advancing": len(finalists), "total": len(candidates)},
        )

        succeeded = 0
        modes: set[AnalysisMode] = set()
        shortlist: list[dict[str, object]] = []
        _emit(progress_callback, "diligence_start", {"total": len(finalists)})
        for finalist_idx, candidate in enumerate(finalists, start=1):
            _emit(
                progress_callback,
                "finalist_start",
                {
                    "index": finalist_idx,
                    "total": len(finalists),
                    "name": candidate.name,
                    "slug": candidate.slug,
                },
            )
            try:
                yc_ev = yc_evidence(candidate)
                if deep_diligence:
                    agent = DeepDiligenceAgent(
                        max_hops=max_hops,
                        offline=offline,
                        progress_callback=progress_callback,
                    )
                    dstate = agent.run(candidate, topic, initial_evidence=yc_ev)
                    evidence = dstate.evidence
                    reach_ev_count = len(evidence) - len(yc_ev)
                else:
                    reach_ev = agent_reach_evidence(candidate, topic, len(yc_ev) + 1)
                    evidence = yc_ev + reach_ev
                    reach_ev_count = len(reach_ev)

                _emit(
                    progress_callback,
                    "finalist_evidence",
                    {
                        "name": candidate.name,
                        "slug": candidate.slug,
                        "count": len(evidence),
                        "yc_count": len(yc_ev),
                        "reach_count": reach_ev_count,
                        "deep_diligence": deep_diligence,
                    },
                )
                _emit(
                    progress_callback,
                    "finalist_synthesis_start",
                    {
                        "name": candidate.name,
                        "slug": candidate.slug,
                        "model": resolved_synthesis_model,
                    },
                )
                result = synthesize(
                    candidate,
                    evidence,
                    self.client,
                    provider=provider,
                    model=resolved_synthesis_model,
                    bedrock_client=bedrock_client,
                )
                modes.add(result.analysis_mode)
                _write_json(
                    output / "evidence" / f"{candidate.slug}.json",
                    [item.model_dump(mode="json") for item in evidence],
                )
                _write_json(output / "analyses" / f"{candidate.slug}.json", result.model_dump(mode="json"))
                memo_file = output / "memos" / f"{candidate.slug}.md"
                memo_file.write_text(
                    render_memo(candidate, result, evidence), encoding="utf-8"
                )
                pdf_file = output / "memos" / f"{candidate.slug}.pdf"
                render_pdf_memo(candidate, result, evidence, pdf_file)
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
                _emit(
                    progress_callback,
                    "finalist_success",
                    {
                        "name": candidate.name,
                        "slug": candidate.slug,
                        "decision": result.recommendation.value,
                        "score": result.score,
                        "confidence": result.confidence,
                        "memo_path": str(memo_file),
                        "pdf_memo_path": str(pdf_file),
                    },
                )
                LOGGER.info("candidate completed candidate=%r", candidate.slug)
            except Exception as error:
                err_msg = _safe_stage_error(error, "finalist")
                failed_slugs.add(candidate.slug)
                gaps.append(
                    {
                        "candidate": candidate.slug,
                        "stage": "finalist",
                        "error": err_msg,
                    }
                )
                _emit(
                    progress_callback,
                    "finalist_failure",
                    {
                        "name": candidate.name,
                        "slug": candidate.slug,
                        "error": err_msg,
                    },
                )
                LOGGER.warning("candidate failed stage=finalist candidate=%r", candidate.slug)
        _write_json(output / "shortlist.json", shortlist)
        _emit(progress_callback, "summary_table", {})

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
            "evidence_sources": enabled_manifest_sources(
                ["yc", "agent_reach", "deep_diligence"] if deep_diligence else ["yc", "agent_reach"]
            ),
            "deep_diligence": deep_diligence,
            "max_hops": max_hops if deep_diligence else 1,
            "provider": provider,
            "analysis_mode": _summarize_modes(modes),
            "screening_model": model_name_for_artifact(resolved_screening_model),
            "synthesis_model": model_name_for_artifact(resolved_synthesis_model),
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

    def replay(
        self,
        run_dir: Path,
        *,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
        request_id: str | None = None,
    ) -> RunSummary:
        """Re-generate both markdown and PDF investment memos from stored run artifacts."""
        run_dir = run_dir.resolve()
        if not run_dir.is_dir():
            raise AppError(f"run directory not found: {run_dir}", exit_code=2)

        candidates_file = run_dir / "candidates.json"
        analyses_dir = run_dir / "analyses"
        evidence_dir = run_dir / "evidence"
        memos_dir = run_dir / "memos"

        if not candidates_file.is_file():
            raise AppError(f"missing candidates.json in {run_dir}", exit_code=2)
        if not analyses_dir.is_dir():
            raise AppError(f"missing analyses directory in {run_dir}", exit_code=2)
        if not evidence_dir.is_dir():
            raise AppError(f"missing evidence directory in {run_dir}", exit_code=2)

        memos_dir.mkdir(parents=True, exist_ok=True)

        try:
            candidates_data = json.loads(candidates_file.read_text(encoding="utf-8"))
            candidates = [Candidate.model_validate(c) for c in candidates_data]
        except Exception as error:
            raise AppError(f"failed to load candidates.json: {error}", exit_code=3) from error

        candidate_by_slug = {c.slug: c for c in candidates}
        analysis_files = sorted(analyses_dir.glob("*.json"))
        if not analysis_files:
            raise AppError(f"no analysis files found in {analyses_dir}", exit_code=2)

        _emit(
            progress_callback,
            "replay_header",
            {
                "run_dir": str(run_dir),
                "total_analyses": len(analysis_files),
            },
        )

        succeeded = 0
        failed = 0
        selected = 0
        shortlist: list[dict[str, object]] = []

        for analysis_file in analysis_files:
            slug = analysis_file.stem
            candidate = candidate_by_slug.get(slug)
            if not candidate:
                LOGGER.warning("candidate with slug %s not found in candidates.json, skipping", slug)
                failed += 1
                continue

            evidence_file = evidence_dir / f"{slug}.json"
            if not evidence_file.is_file():
                LOGGER.warning("evidence file %s not found, skipping", evidence_file)
                failed += 1
                continue

            try:
                analysis_data = json.loads(analysis_file.read_text(encoding="utf-8"))
                analysis = Analysis.model_validate(analysis_data)
                evidence_data = json.loads(evidence_file.read_text(encoding="utf-8"))
                evidence = [Evidence.model_validate(e) for e in evidence_data]

                # Render markdown memo
                md_path = memos_dir / f"{slug}.md"
                md_path.write_text(render_memo(candidate, analysis, evidence), encoding="utf-8")

                # Render PDF memo
                pdf_path = memos_dir / f"{slug}.pdf"
                render_pdf_memo(candidate, analysis, evidence, pdf_path)

                if analysis.recommendation != Recommendation.PASS:
                    selected += 1
                    shortlist.append(
                        {
                            "slug": candidate.slug,
                            "score": analysis.score,
                            "confidence": analysis.confidence,
                            "recommendation": analysis.recommendation,
                        }
                    )

                succeeded += 1
                _emit(
                    progress_callback,
                    "finalist_success",
                    {
                        "name": candidate.name,
                        "slug": candidate.slug,
                        "decision": analysis.recommendation.value,
                        "score": analysis.score,
                        "confidence": analysis.confidence,
                        "memo_path": str(md_path),
                        "pdf_memo_path": str(pdf_path),
                    },
                )
            except Exception as error:
                failed += 1
                LOGGER.warning("failed to replay memo for %s: %s", slug, error)

        # Update shortlist.json if present
        if (run_dir / "shortlist.json").exists() or shortlist:
            _write_json(run_dir / "shortlist.json", shortlist)

        # Update manifest.json if present
        manifest_file = run_dir / "manifest.json"
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        req_id = request_id or "replay"
        if manifest_file.is_file():
            try:
                manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                run_id = manifest_data.get("run_id", run_id)
                req_id = request_id or manifest_data.get("request_id", req_id)
                manifest_data["replayed_at"] = datetime.now(timezone.utc).isoformat()
                manifest_data["succeeded"] = succeeded
                manifest_data["failed"] = failed
                manifest_data["selected"] = selected
                _write_json(manifest_file, manifest_data)
            except Exception:
                pass

        _emit(progress_callback, "summary_table", {})

        summary = RunSummary(
            run_id=run_id,
            request_id=req_id,
            output=str(run_dir),
            candidates=len(candidates),
            screened=len(candidates),
            finalists=len(analysis_files),
            selected=selected,
            succeeded=succeeded,
            failed=failed,
        )
        LOGGER.info(
            "replay completed candidates=%d finalists=%d succeeded=%d failed=%d",
            summary.candidates,
            summary.finalists,
            summary.succeeded,
            summary.failed,
        )
        return summary
