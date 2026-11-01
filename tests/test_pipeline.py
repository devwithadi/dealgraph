import json
from pathlib import Path

import httpx
import pytest

from dealgraph.core.logging import configure_logging
from dealgraph.domain.models import Candidate
from dealgraph.pipeline.service import Pipeline
from dealgraph.sourcing.evidence import hn_evidence
from dealgraph.sourcing.policy import SafeFetcher, SourcePolicyError


FIXTURE = Path(__file__).parent / "fixtures" / "yc.json"


def test_pipeline_runs_source_to_memo_with_mocked_http(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "agentdesk.example" and request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /", request=request)
        if request.url.host == "agentdesk.example":
            return httpx.Response(
                200,
                text=(
                    "<html><head><title>AgentDesk</title></head><body>"
                    "<main><h1>Resolve 70% of support tickets</h1>"
                    "<p>Plans start at $99 per month for small businesses.</p></main>"
                    "</body></html>"
                ),
                headers={"content-type": "text/html"},
                request=request,
            )
        if request.url.host == "hn.algolia.com":
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {
                            "objectID": "42",
                            "title": "Show HN: AgentDesk",
                            "url": "https://agentdesk.example",
                            "points": 83,
                            "num_comments": 21,
                            "created_at": "2025-02-01T00:00:00Z",
                        }
                    ]
                },
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = Pipeline(
        client=client,
        resolver=lambda _host: ["93.184.216.34"],
    ).run(
        topic="AI agents for SMBs",
        batch="W25",
        limit=1,
        output=tmp_path,
        source_file=FIXTURE,
        request_id="req-pipeline-test",
    )

    assert result.succeeded == 1
    assert result.failed == 0
    assert result.request_id == "req-pipeline-test"
    assert requests
    assert {request.headers["x-kong-request-id"] for request in requests} == {
        "req-pipeline-test"
    }
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["request_id"] == "req-pipeline-test"
    assert manifest["analysis_mode"] == "deterministic_fallback"
    assert (tmp_path / "evidence" / "agentdesk.json").exists()
    assert (tmp_path / "analyses" / "agentdesk.json").exists()
    analysis = json.loads((tmp_path / "analyses" / "agentdesk.json").read_text())
    assert {"team", "product", "market", "why_now", "risks", "open_questions"} <= analysis.keys()
    assert analysis["financials"]["revenue"] is None
    assert 0 <= analysis["score"] <= 100
    assert len(analysis["changes_mind"]) == 3
    memo = (tmp_path / "memos" / "agentdesk.md").read_text()
    assert "# AgentDesk — Investment Memo" in memo
    assert "Pass\n" in memo or "Watch\n" in memo or "Take a meeting\n" in memo
    assert "https://agentdesk.example" in memo
    assert "ev-001" in next(line for line in memo.splitlines() if "Pain Roi" in line)


def test_fetcher_revalidates_redirects_and_obeys_robots() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /secret", request=request)
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"}, request=request)
        raise AssertionError(f"Page should not be fetched: {request.url}")

    fetcher = SafeFetcher(
        httpx.Client(transport=httpx.MockTransport(handler)),
        resolver=lambda _host: ["93.184.216.34"],
    )
    with pytest.raises(SourcePolicyError, match="Non-public"):
        fetcher.html("https://public.example/redirect")
    with pytest.raises(SourcePolicyError, match="robots.txt"):
        fetcher.html("https://public.example/secret")
    assert not any(url.endswith("/private") or url.endswith("/secret") for url in requested)


def test_offline_pipeline_never_uses_network(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")

    def fail_on_request(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"offline mode attempted network: {request.url}")

    result = Pipeline(client=httpx.Client(transport=httpx.MockTransport(fail_on_request))).run(
        topic="AI agents for SMBs",
        batch="W25",
        limit=1,
        output=tmp_path,
        source_file=FIXTURE,
        offline=True,
    )
    assert result.succeeded == 1
    evidence = json.loads((tmp_path / "evidence" / "agentdesk.json").read_text())
    assert evidence[0]["verification"] == "third_party"
    analysis = json.loads((tmp_path / "analyses" / "agentdesk.json").read_text())
    assert analysis["analysis_mode"] == "deterministic_fallback"
    assert analysis["financials"] == {
        "revenue": None,
        "burn": None,
        "runway": None,
        "funding": None,
        "pricing": None,
        "evidence_ids": [],
    }


def test_verbose_pipeline_logs_unexpected_candidate_traceback(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        "dealgraph.pipeline.service.render_memo",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("render broke")),
    )
    configure_logging(verbose=True)

    result = Pipeline().run(
        topic="AI agents for SMBs",
        batch="W25",
        limit=1,
        output=tmp_path,
        source_file=FIXTURE,
        offline=True,
        request_id="req-render-failure",
    )

    assert result.failed == 1
    stderr = capsys.readouterr().err
    assert "candidate failed stage=pipeline" in stderr
    assert "Traceback" in stderr


def test_hn_evidence_ignores_unrelated_hits() -> None:
    candidate = Candidate(
        slug="agentdesk",
        name="AgentDesk",
        website="https://agentdesk.example",
        one_liner="AI agents for support teams",
        source_url="https://www.ycombinator.com/companies/agentdesk",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "hn.algolia.com"
        return httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "objectID": "999",
                        "title": "Agent desk setup tips",
                        "url": "https://other.example/post",
                        "points": 999,
                        "num_comments": 999,
                        "created_at": "2026-08-01T00:00:00Z",
                    },
                    {
                        "objectID": "42",
                        "title": "Show HN: AgentDesk",
                        "url": "https://agentdesk.example/blog/launch",
                        "points": 12,
                        "num_comments": 3,
                        "created_at": "2026-08-02T00:00:00Z",
                    },
                ]
            },
            request=request,
        )

    evidence = hn_evidence(
        candidate,
        httpx.Client(transport=httpx.MockTransport(handler)),
        evidence_id=2,
    )

    assert evidence[0].source_url == "https://news.ycombinator.com/item?id=42"


def test_pipeline_fetches_yc_feed_when_source_file_is_omitted(tmp_path: Path) -> None:
    with FIXTURE.open() as handle:
        yc_payload = json.load(handle)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "yc-oss.github.io":
            return httpx.Response(200, json=yc_payload, request=request)
        if request.url.host == "agentdesk.example" and request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /", request=request)
        if request.url.host == "agentdesk.example":
            return httpx.Response(
                200,
                text="<html><head><title>AgentDesk</title></head><body>Support automation for SMBs</body></html>",
                headers={"content-type": "text/html"},
                request=request,
            )
        if request.url.host == "hn.algolia.com":
            return httpx.Response(200, json={"hits": []}, request=request)
        raise AssertionError(f"Unexpected request: {request.url}")

    result = Pipeline(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        resolver=lambda _host: ["93.184.216.34"],
    ).run(
        topic="AI agents for SMBs",
        batch="W25",
        limit=1,
        output=tmp_path,
    )

    assert result.succeeded == 1
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["candidate_source"] == "https://yc-oss.github.io/api/companies/all.json"
