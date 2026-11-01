import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.domain.enums import AIProvider, AnalysisMode
from app.domain.models import Evidence
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


def test_pipeline_runs_two_stage_flow_and_writes_auditable_artifacts(
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
    result = Pipeline().run(
        topic="AI agents for SMBs",
        batch=None,
        limit=None,
        output=tmp_path / "run",
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
    run = tmp_path / "run"
    assert json.loads((run / "screenings.json").read_text())[0]["advance"] is True
    assert json.loads((run / "shortlist.json").read_text())[0]["recommendation"] == "Watch"
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["lookback_days"] == 30
    assert manifest["selected"] == 1
    assert manifest["screening_model"] == "amazon.nova-micro-v1:0"
    assert manifest["synthesis_model"] == "amazon.nova-lite-v1:0"
    assert manifest["screening_prompt_version"] == "screening-v5"
    assert manifest["synthesis_prompt_version"] == "synthesis-v4"
    assert manifest["evidence_sources"] == [YC_URL, "Agent Reach / Exa web search"]
    memo = (run / "memos" / "agentdesk.md").read_text()
    assert "WATCH" in memo
    assert "[INVESTMENT COMMITTEE MEMO]" in memo
    assert "https://news.example/agentdesk" in memo
    assert (run / "memos" / "agentdesk.pdf").exists()
    assert (run / "memos" / "agentdesk.pdf").stat().st_size > 0


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


def test_pipeline_replay_regenerates_markdown_and_pdf_without_llm_or_network(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "yc.json"
    source.write_text(json.dumps([record()]), encoding="utf-8")

    monkeypatch.setattr(
        "app.pipeline.service.agent_reach_evidence",
        lambda *_args: [
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
        ],
    )
    client = BedrockClient()
    run_dir = tmp_path / "run"
    result = Pipeline(bedrock_client=client).run(
        topic="AI agents for SMBs",
        batch=None,
        limit=None,
        output=run_dir,
        source_file=source,
        request_id="req-first-run",
        now=NOW,
    )
    assert result.succeeded == 1

    # Remove the rendered memos to verify replay re-generates them
    memo_md = run_dir / "memos" / "agentdesk.md"
    memo_pdf = run_dir / "memos" / "agentdesk.pdf"
    assert memo_md.exists()
    assert memo_pdf.exists()
    memo_md.unlink()
    memo_pdf.unlink()
    assert not memo_md.exists()
    assert not memo_pdf.exists()

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
    assert memo_md.exists()
    assert memo_pdf.exists()
    assert memo_pdf.stat().st_size > 0
    assert "[INVESTMENT COMMITTEE MEMO]" in memo_md.read_text(encoding="utf-8")


def test_pipeline_run_offline_invokes_replay_when_run_artifacts_exist(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "yc.json"
    source.write_text(json.dumps([record()]), encoding="utf-8")

    monkeypatch.setattr(
        "app.pipeline.service.agent_reach_evidence",
        lambda *_args: [
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
        ],
    )
    run_dir = tmp_path / "run"
    Pipeline(bedrock_client=BedrockClient()).run(
        topic="AI agents for SMBs",
        batch=None,
        limit=None,
        output=run_dir,
        source_file=source,
        request_id="req-first-run",
        now=NOW,
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

