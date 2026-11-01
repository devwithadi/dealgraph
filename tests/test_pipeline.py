import json
from pathlib import Path

import httpx

from app.pipeline import Pipeline


FIXTURE = Path(__file__).parent / "fixtures" / "yc.json"


def test_pipeline_runs_source_to_memo_with_mocked_http(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
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
    )

    assert result.succeeded == 1
    assert result.failed == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["analysis_mode"] == "deterministic_fallback"
    assert (tmp_path / "evidence" / "agentdesk.json").exists()
    assert (tmp_path / "analyses" / "agentdesk.json").exists()
    memo = (tmp_path / "memos" / "agentdesk.md").read_text()
    assert "# AgentDesk — Investment Memo" in memo
    assert "Pass\n" in memo or "Watch\n" in memo or "Take a meeting\n" in memo
    assert "https://agentdesk.example" in memo
