from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.analysis.diligence import DeepDiligenceAgent, evaluate_diligence
from app.analysis.diligence.constants import DILIGENCE
from app.analysis.providers import (
    model_for,
    model_json,
    model_name_for_artifact,
    screening_model_for,
    validate_provider_config,
)
from app.analysis.service import screen_candidates, synthesize
from app.core.errors import AppError
from app.core.logging import bind_request_id, request_headers
from app.domain.enums import AIProvider, AnalysisMode, Recommendation
from app.domain.models import RunSummary, ScreeningDecision
from app.prompts.screening import build_discovery_prompt
from app.reporting.pdf import render_pdf_memo
from app.sourcing.candidates import (
    discover_candidates,
    load_candidates,
    lookback_days_from_env,
)
from app.sourcing.constants import AGENT_REACH
from app.sourcing.evidence import agent_reach_evidence, candidate_evidence
from app.sourcing.registry import YC_URL, source_enabled

LOGGER = logging.getLogger("dealgraph.pipeline")
SCREENING_BATCH_SIZE = 20


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


def _write_json(path: Path, value: Any) -> None:
    """Write a JSON artifact atomically so interrupted runs do not leave partial files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


class Pipeline:
    def __init__(
        self,
        client: httpx.Client | None = None,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(10, connect=5),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=5),
            transport=httpx.HTTPTransport(retries=2),
        )

    def run(
        self,
        *,
        topic: str,
        batch: str | None,
        limit: int | None,
        output: Path,
        source_file: Path | None = None,
        request_id: str | None = None,
        provider: AIProvider = AIProvider.BEDROCK,
        screening_model: str | None = None,
        synthesis_model: str | None = None,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
        now: datetime | None = None,
        deep_diligence: bool = False,
        max_hops: int = DILIGENCE.default_max_hops,
    ) -> RunSummary:
        request_id = bind_request_id(request_id)
        LOGGER.info("run started deep_diligence=%s", deep_diligence)
        if not topic.strip():
            raise AppError("topic cannot be empty", exit_code=2)
        validate_provider_config(
            provider,
            screening_model,
            synthesis_model,
        )
        resolved_screening_model = screening_model_for(provider, screening_model) or ""
        resolved_synthesis_model = model_for(provider, synthesis_model) or ""
        lookback_days = lookback_days_from_env()
        effective_now = now or datetime.now(timezone.utc)
        cutoff = effective_now - timedelta(days=lookback_days)
        output = output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        (output / "evidence").mkdir(exist_ok=True)
        (output / "analyses").mkdir(exist_ok=True)
        safe_screening_model = model_name_for_artifact(resolved_screening_model)
        safe_synthesis_model = model_name_for_artifact(resolved_synthesis_model)
        _write_json(
            output / "input.json",
            {
                "topic": topic,
                "batch": batch,
                "limit": limit,
                "source_file": source_file.name if source_file else None,
                "provider": provider.value,
                "screening_model": safe_screening_model,
                "synthesis_model": safe_synthesis_model,
                "lookback_days": lookback_days,
                "cutoff": cutoff.isoformat(),
                "deep_diligence": deep_diligence,
                "max_hops": max_hops,
                "request_id": request_id,
            },
        )

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

            def structured_agent_reach_output(raw_results: str) -> Mapping[str, object]:
                return model_json(
                    build_discovery_prompt(raw_results, topic),
                    provider=provider,
                    model=resolved_screening_model,
                    max_tokens=AGENT_REACH.discovery_model_max_tokens,
                    stage="discovery",
                )

            candidates = discover_candidates(
                topic=topic,
                batch=batch,
                lookback_days=lookback_days,
                client=self.client,
                yc_records=yc_records,
                structured_output=structured_agent_reach_output,
                now=effective_now,
                limit=limit,
            )
            if not candidates:
                raise AppError("Unable to load candidate startups from sourcing channels", exit_code=3)
            source_names = ["YC Directory"] if yc_records else []
            if source_enabled("hacker_news"):
                source_names.append("Hacker News")
            if source_enabled("agent_reach"):
                source_names.append("Agent Reach / Exa")
            source = " + ".join(source_names) or "enabled public sources"

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
            output / "candidates.json",
            [candidate.model_dump(mode="json") for candidate in candidates],
        )

        screenings: list[ScreeningDecision] = []
        gaps: list[dict[str, Any]] = []
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
                    provider=provider,
                    model=resolved_screening_model,
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

        candidate_by_slug = {candidate.slug: candidate for candidate in candidates}
        finalists = [candidate_by_slug[item.slug] for item in screenings if item.advance]
        _write_json(
            output / "screenings.json",
            [decision.model_dump(mode="json") for decision in screenings],
        )
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
                baseline_ev = candidate_evidence(candidate)
                if deep_diligence:
                    def evaluate(candidate_to_evaluate, evidence_to_evaluate, evaluation_topic, hop):
                        return evaluate_diligence(
                            candidate_to_evaluate,
                            evidence_to_evaluate,
                            evaluation_topic,
                            hop,
                            provider=provider,
                            model=resolved_screening_model,
                        )

                    agent = DeepDiligenceAgent(
                        evaluation_fn=evaluate,
                        max_hops=max_hops,
                        progress_callback=progress_callback,
                    )
                    dstate = agent.run(candidate, topic, initial_evidence=baseline_ev)
                    evidence = dstate.evidence
                    gaps.extend(
                        {"candidate": candidate.slug, **gap.model_dump(mode="json")}
                        for gap in dstate.gaps
                    )
                    reach_ev_count = len(evidence) - len(baseline_ev)
                else:
                    reach_ev = agent_reach_evidence(candidate, topic, len(baseline_ev) + 1)
                    evidence = baseline_ev + reach_ev
                    reach_ev_count = len(reach_ev)

                _write_json(
                    output / "evidence" / f"{candidate.slug}.json",
                    [item.model_dump(mode="json") for item in evidence],
                )

                _emit(
                    progress_callback,
                    "finalist_evidence",
                    {
                        "name": candidate.name,
                        "slug": candidate.slug,
                        "count": len(evidence),
                        "baseline_count": len(baseline_ev),
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
                    provider=provider,
                    model=resolved_synthesis_model,
                )
                _write_json(
                    output / "analyses" / f"{candidate.slug}.json",
                    result.model_dump(mode="json"),
                )
                modes.add(result.analysis_mode)
                pdf_file = output / f"{candidate.slug}.pdf"
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
        _emit(progress_callback, "summary_table", {})

        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
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
        _write_json(output / "shortlist.json", shortlist)
        _write_json(output / "gaps.json", gaps)
        _write_json(
            output / "manifest.json",
            {
                "run_id": run_id,
                "request_id": request_id,
                "topic": topic,
                "provider": provider.value,
                "screening_model": safe_screening_model,
                "synthesis_model": safe_synthesis_model,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "summary": {**summary.model_dump(mode="json"), "output": "."},
                "artifacts": {
                    "input": "input.json",
                    "candidates": "candidates.json",
                    "screenings": "screenings.json",
                    "evidence": "evidence/",
                    "analyses": "analyses/",
                    "shortlist": "shortlist.json",
                    "gaps": "gaps.json",
                },
            },
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
