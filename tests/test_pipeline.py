import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.domain.enums import AIProvider, AnalysisMode, Recommendation
from app.domain.models import Analysis, Evidence, Financials
from app.pipeline.service import Pipeline, _summarize_modes
from app.sourcing.registry import YC_URL


NOW = datetime(2026, 8, 23, tzinfo=timezone.utc)


def record(slug: str = "agentdesk") -> dict:
    return {
        "id": slug,
        "slug": slug,
        "name": "AgentDesk",
        "website": "https://agentdesk.example",
        "one_liner": "AI agents that automate support workflows for SMBs",
        "long_description": "Support automation platform",
        "batch": "Summer 2026",
        "status": "Active",
        "launched_at": int(NOW.timestamp()),
    }


def candidate_record(slug: str = "agentdesk") -> dict:
    return {
        "slug": slug,
        "name": "AgentDesk",
        "website": "https://agentdesk.example",
        "one_liner": "AI agents that automate support workflows for SMBs",
        "description": "Support automation platform",
        "batch": "Summer 2026",
        "launched_at": NOW.isoformat(),
        "source_url": "https://ycombinator.com/companies/agentdesk",
    }


class BedrockClient:
    def converse(self, **kwargs):
        stage = kwargs["requestMetadata"]["stage"]
        if stage == "screening":
            payload = {
                "decisions": [
                    {
                        "slug": "agentdesk",
                        "advance": True,
                        "fit_score": 85,
                        "rationale": "Strong fit",
                    }
                ]
            }
        else:
            payload = {
                "summary": "Strong fit with evidence gaps. [ev-001]",
                "team": "Unknown",
                "product": "AI support automation. [ev-001]",
                "market": "SMB support. [ev-001]",
                "why_now": "AI adoption. [ev-001]",
                "risks": ["Retention is unknown. [ev-001]"],
                "open_questions": ["What is retention?"],
                "changes_mind": ["Verified retention", "Customer references"],
                "score": 71,
                "confidence": 0.6,
                "recommendation": "Watch",
                "citations": ["ev-001", "ev-002"],
            }
        return {"output": {"message": {"content": [{"text": json.dumps(payload)}]}}}


def test_pipeline_runs_two_stage_flow_and_writes_pdf_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "yc.json"
    source.write_text(json.dumps([record()]), encoding="utf-8")

    def research(candidate, _topic, _start):
        return [
            Evidence(
                id="ev-002",
                claim="Agent Reach result",
                excerpt="A customer pilot was announced.",
                source_url="https://news.example/agentdesk",
                source_title="Customer pilot",
                source_type="agent_reach",
                trust_tier="open_web",
                verification="third_party_search",
            )
        ]

    monkeypatch.setattr("app.pipeline.service.agent_reach_evidence", research)
    client = BedrockClient()
    created: list[object] = []

    def create_client():
        created.append(client)
        return client

    monkeypatch.setattr("app.pipeline.service.create_bedrock_client", create_client)
    run_dir = tmp_path / "run"
    result = Pipeline().run(
        topic="AI agents for SMBs",
        batch=None,
        limit=None,
        output=run_dir,
        source_file=source,
        request_id="req-pipeline",
        now=NOW,
    )

    assert result.model_dump() | {"output": "ignored"} == {
        "run_id": result.run_id,
        "request_id": "req-pipeline",
        "output": "ignored",
        "candidates": 1,
        "screened": 1,
        "finalists": 1,
        "selected": 1,
        "succeeded": 1,
        "failed": 0,
    }
    assert created == [client]
    # Only PDF is outputted in run directory
    pdf_path = run_dir / "agentdesk.pdf"
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    assert not (run_dir / "memos").exists()
    assert not (run_dir / "manifest.json").exists()
    assert not (run_dir / "candidates.json").exists()
    assert not (run_dir / "screenings.json").exists()
    assert not (run_dir / "shortlist.json").exists()
    assert not (run_dir / "evidence").exists()
    assert not (run_dir / "analyses").exists()


def test_pipeline_fetches_yc_feed_before_llm_screening(tmp_path: Path, monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[record()], request=request)

    monkeypatch.setattr(
        "app.pipeline.service.agent_reach_evidence",
        lambda *_args: [
            Evidence(
                id="ev-002",
                claim="Research",
                excerpt="Evidence",
                source_url="https://news.example",
                source_title="News",
                source_type="agent_reach",
                trust_tier="open_web",
                verification="third_party_search",
            )
        ],
    )
    result = Pipeline(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        bedrock_client=BedrockClient(),
    ).run(
        topic="AI",
        batch=None,
        limit=None,
        output=tmp_path,
        now=NOW,
    )

    assert result.succeeded == 1
    assert requests[0].url == YC_URL
    assert requests[0].headers["x-kong-request-id"] == result.request_id


def test_mixed_provider_results_are_reported_as_mixed() -> None:
    assert _summarize_modes({AnalysisMode.BEDROCK, AnalysisMode.OPENAI}) == AnalysisMode.MIXED


def test_pipeline_replay_regenerates_pdf_without_llm_or_network(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "analyses").mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence").mkdir(parents=True, exist_ok=True)

    (run_dir / "candidates.json").write_text(
        json.dumps([candidate_record()]), encoding="utf-8"
    )
    analysis = Analysis(
        company="AgentDesk",
        thesis="Strong fit with evidence gaps. [ev-001]",
        summary="Strong fit with evidence gaps. [ev-001]",
        team="Unknown",
        product="AI support automation. [ev-001]",
        market="SMB support. [ev-001]",
        why_now="AI adoption. [ev-001]",
        financials=Financials(),
        risks=["Retention is unknown. [ev-001]"],
        open_questions=["What is retention?"],
        changes_mind=["Verified retention", "Customer references"],
        score=71.0,
        confidence=0.6,
        recommendation=Recommendation.WATCH,
        analysis_mode=AnalysisMode.BEDROCK,
    )
    (run_dir / "analyses" / "agentdesk.json").write_text(
        json.dumps(analysis.model_dump(mode="json")),
        encoding="utf-8",
    )
    (run_dir / "evidence" / "agentdesk.json").write_text(
        json.dumps(
            [
                {
                    "id": "ev-001",
                    "claim": "YC Company Profile",
                    "excerpt": "AgentDesk support automation platform.",
                    "source_url": "https://ycombinator.com/companies/agentdesk",
                    "source_title": "YC Directory",
                    "source_type": "yc_directory",
                    "trust_tier": "curated_directory",
                    "verification": "third_party",
                    "status": "verified",
                }
            ]
        ),
        encoding="utf-8",
    )

    # Any LLM or network call during replay must raise an error
    def forbidden(*_args, **_kwargs):
        raise AssertionError("replay must not make any LLM or network calls")

    monkeypatch.setattr("app.pipeline.service.screen_candidates", forbidden)
    monkeypatch.setattr("app.pipeline.service.agent_reach_evidence", forbidden)
    monkeypatch.setattr("app.pipeline.service.synthesize", forbidden)

    replay_summary = Pipeline(
        client=httpx.Client(transport=httpx.MockTransport(forbidden)),
        bedrock_client=None,
    ).replay(run_dir, request_id="req-replay")

    assert replay_summary.succeeded == 1
    assert replay_summary.failed == 0
    assert replay_summary.selected == 1
    pdf_path = run_dir / "agentdesk.pdf"
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0


def test_pipeline_run_offline_invokes_replay_when_run_artifacts_exist(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "analyses").mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence").mkdir(parents=True, exist_ok=True)

    (run_dir / "candidates.json").write_text(
        json.dumps([candidate_record()]), encoding="utf-8"
    )
    analysis = Analysis(
        company="AgentDesk",
        thesis="Strong fit with evidence gaps. [ev-001]",
        summary="Strong fit. [ev-001]",
        team="Unknown",
        product="AI support. [ev-001]",
        market="SMB support. [ev-001]",
        why_now="AI. [ev-001]",
        financials=Financials(),
        risks=["Retention is unknown. [ev-001]"],
        open_questions=["What is retention?"],
        changes_mind=["Verified retention", "Customer references"],
        score=71.0,
        confidence=0.6,
        recommendation=Recommendation.WATCH,
        analysis_mode=AnalysisMode.BEDROCK,
    )
    (run_dir / "analyses" / "agentdesk.json").write_text(
        json.dumps(analysis.model_dump(mode="json")),
        encoding="utf-8",
    )
    (run_dir / "evidence" / "agentdesk.json").write_text(
        json.dumps(
            [
                {
                    "id": "ev-001",
                    "claim": "YC Profile",
                    "excerpt": "Snippet",
                    "source_url": "https://ycombinator.com",
                    "source_title": "YC",
                    "source_type": "yc_directory",
                    "trust_tier": "curated_directory",
                    "verification": "third_party",
                    "status": "verified",
                }
            ]
        ),
        encoding="utf-8",
    )

    # Calling run with offline=True on existing run directory should succeed via replay
    result = Pipeline().run(
        topic="AI agents for SMBs",
        batch=None,
        limit=None,
        output=run_dir,
        offline=True,
    )
    assert result.succeeded == 1
    assert result.failed == 0
    assert (run_dir / "agentdesk.pdf").exists()
