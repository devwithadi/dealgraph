import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app.core.errors import AppError
from app.domain.enums import AIProvider, AnalysisMode, Recommendation
from app.domain.models import Analysis, Evidence, Financials, ScreeningDecision
from app.pipeline.service import Pipeline
from app.sourcing.candidates import lookback_days_from_env, select_candidates


NOW = datetime(2026, 8, 23, tzinfo=timezone.utc)


def _record(slug: str, age_days: int | None, one_liner: str = "Unrelated product") -> dict:
    return {
        "id": slug,
        "slug": slug,
        "name": slug.title(),
        "website": f"https://{slug}.example",
        "one_liner": one_liner,
        "long_description": "A company description",
        "batch": "Summer 2026",
        "status": "Active",
        "launched_at": (
            int((NOW - timedelta(days=age_days)).timestamp())
            if age_days is not None
            else None
        ),
    }


def test_candidate_window_ignores_topic_and_has_no_twenty_company_cap() -> None:
    records = [_record(f"company-{index}", index) for index in range(25)]
    records.extend(
        [
            _record("cutoff", 30),
            _record("stale-keyword-match", 31, "Perfect AI agent for SMBs"),
            _record("undated", None, "Perfect AI agent for SMBs"),
        ]
    )

    selected = select_candidates(
        records,
        batch=None,
        lookback_days=30,
        now=NOW,
    )

    assert len(selected) == 26
    assert selected[0].slug == "company-0"
    assert selected[-1].slug == "cutoff"
    assert "stale-keyword-match" not in {candidate.slug for candidate in selected}
    assert "undated" not in {candidate.slug for candidate in selected}


def test_lookback_days_defaults_to_thirty_and_validates_env(monkeypatch) -> None:
    monkeypatch.delenv("DEALGRAPH_LOOKBACK_DAYS", raising=False)
    assert lookback_days_from_env() == 30

    monkeypatch.setenv("DEALGRAPH_LOOKBACK_DAYS", "45")
    assert lookback_days_from_env() == 45

    for invalid in ("0", "abc", "3651"):
        monkeypatch.setenv("DEALGRAPH_LOOKBACK_DAYS", invalid)
        with pytest.raises(AppError, match="DEALGRAPH_LOOKBACK_DAYS"):
            lookback_days_from_env()


def test_all_recent_candidates_are_screened_but_only_finalists_are_researched(
    tmp_path: Path, monkeypatch
) -> None:
    records = [_record(f"company-{index}", index % 20) for index in range(25)]
    source = tmp_path / "yc.json"
    source.write_text(json.dumps(records), encoding="utf-8")
    screened: list[str] = []
    researched: list[str] = []
    synthesized: list[str] = []

    def fake_screen(candidates, *_args, **_kwargs):
        screened.extend(candidate.slug for candidate in candidates)
        return [
            ScreeningDecision(
                slug=candidate.slug,
                advance=candidate.slug in {"company-3", "company-21"},
                fit_score=80 if candidate.slug in {"company-3", "company-21"} else 20,
                rationale="LLM judgment",
            )
            for candidate in candidates
        ]

    def fake_research(candidate, *_args, **_kwargs):
        researched.append(candidate.slug)
        return [
            Evidence(
                id="ev-001",
                claim="Agent Reach result",
                excerpt="Public evidence",
                source_url=f"https://news.example/{candidate.slug}",
                source_title="Public source",
                source_type="agent_reach",
                trust_tier="open_web",
                verification="third_party",
            )
        ]

    def fake_synthesize(candidate, evidence, *_args, **_kwargs):
        synthesized.append(candidate.slug)
        return Analysis(
            company=candidate.name,
            thesis="Thesis",
            summary="Summary",
            team="Unknown",
            product="Product",
            market="Market",
            why_now="Why now",
            financials=Financials(),
            risks=["Risk"],
            open_questions=["Question"],
            changes_mind=["Evidence one", "Evidence two"],
            score=72,
            confidence=0.6,
            recommendation=Recommendation.WATCH,
            analysis_mode=AnalysisMode.BEDROCK,
        )

    monkeypatch.setenv("DEALGRAPH_LOOKBACK_DAYS", "30")
    monkeypatch.setattr("app.pipeline.service.screen_candidates", fake_screen)
    monkeypatch.setattr("app.pipeline.service.agent_reach_evidence", fake_research)
    monkeypatch.setattr("app.pipeline.service.synthesize", fake_synthesize)
    result = Pipeline(client=httpx.Client()).run(
        topic="AI agents for SMBs",
        batch=None,
        limit=None,
        output=tmp_path / "run",
        source_file=source,
        provider=AIProvider.BEDROCK,
        now=NOW,
    )

    assert len(screened) == 25
    assert set(researched) == {"company-3", "company-21"}
    assert set(synthesized) == set(researched)
    assert result.candidates == 25
    assert result.screened == 25
    assert result.finalists == 2
    assert result.selected == 2
    assert result.succeeded == 2
    assert result.failed == 0
    assert {path.stem for path in (tmp_path / "run" / "memos").glob("*.md")} == set(researched)


def test_offline_llm_pipeline_fails_before_any_network(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "yc.json"
    source.write_text(json.dumps([_record("company", 1)]), encoding="utf-8")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("network/model/research should not be called")

    monkeypatch.setattr("app.pipeline.service.screen_candidates", forbidden)
    monkeypatch.setattr("app.pipeline.service.agent_reach_evidence", forbidden)
    monkeypatch.setattr("app.pipeline.service.synthesize", forbidden)

    with pytest.raises(AppError, match="LLM-only"):
        Pipeline(client=httpx.Client(transport=httpx.MockTransport(forbidden))).run(
            topic="AI",
            batch=None,
            limit=None,
            output=tmp_path / "run",
            source_file=source,
            offline=True,
        )


def test_build_synthesis_prompt_includes_exhaustive_vc_instructions() -> None:
    from app.prompts.synthesis import build_synthesis_prompt

    inputs = {
        "company_name": "Acme AI",
        "sector": "Enterprise Infrastructure",
        "stage": "Seed",
        "requested_valuation": "USD 20m",
        "dealgraph_thesis": "Autonomous database indexing",
        "analysis_date": "2026-08-24",
        "external_evidence": [
            {
                "id": "ev-001",
                "claim": "YC profile",
                "excerpt": "Acme AI raises $4M seed.",
                "source_url": "https://ycombinator.com/companies/acme",
            }
        ],
    }
    prompt = build_synthesis_prompt(inputs)

    assert "Acme AI" in prompt
    assert "Bottom-Up TAM / SAM Breakdown" in prompt
    assert "Biographical Audit" in prompt
    assert "Technical Architecture Deep-Dive" in prompt
    assert "Comprehensive Pricing Breakdown" in prompt
    assert "Critical Failure Scenarios" in prompt
    assert "Crown Jewel Strategic Assessment" in prompt
    assert "The Inverse Case" in prompt
    assert "multi-paragraph" in prompt

