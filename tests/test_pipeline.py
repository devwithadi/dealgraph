import json
import inspect
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.core.errors import AppError
from app.domain.enums import AIProvider, AnalysisMode
from app.domain.models import Evidence
from app.pipeline.service import Pipeline, _summarize_modes
from app.sourcing.registry import YC_URL


NOW = datetime(2026, 8, 23, tzinfo=timezone.utc)


def test_pipeline_has_no_offline_or_replay_surface() -> None:
    assert "offline" not in inspect.signature(Pipeline.run).parameters
    assert not hasattr(Pipeline, "replay")


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


def test_pipeline_runs_two_stage_flow_and_writes_complete_run_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-only")
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
    pdf_path = run_dir / "agentdesk.pdf"
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    assert not (run_dir / "memos").exists()

    candidates = json.loads((run_dir / "candidates.json").read_text(encoding="utf-8"))
    screenings = json.loads((run_dir / "screenings.json").read_text(encoding="utf-8"))
    shortlist = json.loads((run_dir / "shortlist.json").read_text(encoding="utf-8"))
    evidence = json.loads((run_dir / "evidence" / "agentdesk.json").read_text(encoding="utf-8"))
    analysis = json.loads((run_dir / "analyses" / "agentdesk.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    assert [item["slug"] for item in candidates] == ["agentdesk"]
    assert screenings[0]["slug"] == "agentdesk"
    assert shortlist[0]["slug"] == "agentdesk"
    assert {item["id"] for item in evidence} == {"ev-001", "ev-002"}
    assert analysis["company"] == "AgentDesk"
    assert manifest["request_id"] == "req-pipeline"
    assert manifest["topic"] == "AI agents for SMBs"
    assert manifest["summary"]["succeeded"] == 1


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


def test_pipeline_fails_before_network_when_selected_provider_key_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def forbidden(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("credential validation must happen before network access")

    with pytest.raises(AppError, match="OPENAI_API_KEY is required"):
        Pipeline(client=httpx.Client(transport=httpx.MockTransport(forbidden))).run(
            topic="AI agents for SMBs",
            batch=None,
            limit=None,
            output=tmp_path / "run",
            provider=AIProvider.OPENAI,
            now=NOW,
        )


def test_mixed_provider_results_are_reported_as_mixed() -> None:
    assert _summarize_modes({AnalysisMode.BEDROCK, AnalysisMode.OPENAI}) == AnalysisMode.MIXED
