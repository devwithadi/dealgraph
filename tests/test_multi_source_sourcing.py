from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from app.domain.models import Candidate
from app.sourcing.candidates import (
    discover_candidates,
    load_candidates,
    lookback_days_from_env,
    select_candidates,
)
from app.sourcing.discovery import (
    clean_startup_name,
    deduplicate_and_merge_candidates,
    extract_website_from_text,
    fetch_hn_candidates,
    make_candidate_slug,
    normalize_domain,
    parse_url_seed_candidates,
    search_agent_reach_candidates,
)


def test_make_candidate_slug() -> None:
    assert make_candidate_slug("https://trydock.ai/login") == "trydock.ai"
    assert make_candidate_slug("Dock AI (YC W25)") == "dock-ai-yc-w25"
    assert make_candidate_slug("---special---") == "special"
    assert make_candidate_slug("") == "startup"


def test_normalize_domain() -> None:
    assert normalize_domain("https://www.trydock.ai/pricing") == "trydock.ai"
    assert normalize_domain("http://gini.ai") == "gini.ai"
    assert normalize_domain("www.example.com") == "example.com"
    assert normalize_domain("simple-slug") == "simple-slug"
    assert normalize_domain("") == ""


def test_clean_startup_name() -> None:
    name, one_liner = clean_startup_name("Show HN: Dock – Multiplayer agent workspace for SMBs")
    assert name == "Dock"
    assert "Multiplayer agent workspace" in one_liner

    name2, one_liner2 = clean_startup_name("Vortex AI: Real-time fraud detection | Product Hunt")
    assert name2 == "Vortex AI"
    assert "Real-time fraud detection" in one_liner2

    name3, one_liner3 = clean_startup_name("TinyApp")
    assert name3 == "TinyApp"
    assert one_liner3 == "TinyApp"


def test_extract_website_from_text() -> None:
    text = "We just launched our product at https://trydock.ai for early teams. Check producthunt.com/posts/dock too."
    assert extract_website_from_text(text) == "https://trydock.ai"

    text_no_url = "No link here, check later."
    assert extract_website_from_text(text_no_url, fallback_domain="fallback.ai") == "https://fallback.ai"


def test_fetch_hn_candidates_success() -> None:
    mock_response_data = {
        "hits": [
            {
                "objectID": "12345",
                "title": "Show HN: Dock – Autonomous multiplayer workspace",
                "url": "https://trydock.ai",
                "author": "aditya",
                "points": 185,
                "num_comments": 64,
                "created_at": "2026-08-15T12:00:00Z",
                "story_text": "We are hiring engineers to build collaborative AI workspaces.",
            },
            {
                "objectID": "67890",
                "title": "Show HN: Gini – AI CFO for SMBs",
                "url": None,
                "author": "founder2",
                "points": 95,
                "num_comments": 30,
                "created_at": "2026-08-18T14:30:00Z",
                "story_text": "Website: https://gini.ai. Automating SMB bookkeeping.",
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_response_data, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    candidates = fetch_hn_candidates("AI agents", client=client, limit=5)

    assert len(candidates) == 2
    assert candidates[0].name == "Dock"
    assert candidates[0].website == "https://trydock.ai"
    assert candidates[0].is_hiring is True
    assert "Show HN" in candidates[0].batch
    assert candidates[0].source_url == "https://news.ycombinator.com/item?id=12345"

    assert candidates[1].name == "Gini"
    assert candidates[1].website == "https://gini.ai"


def test_fetch_hn_candidates_error_handling() -> None:
    def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    client = httpx.Client(transport=httpx.MockTransport(error_handler))
    assert fetch_hn_candidates("test", client=client) == []


def test_search_agent_reach_candidates_success() -> None:
    mock_stdout = """Title: Dock: AI agents that do real work | Product Hunt
URL: https://www.producthunt.com/products/dock
Highlights: Dock is the collaborative workspace for AI teammates (https://trydock.ai). Voted #2 Product of the Day with 380 upvotes. We are hiring.
---
Title: SynthFlow - Voice AI agents for SMB support
URL: https://synthflow.ai
Highlights: SynthFlow provides conversational voice agents for SMB customer support. Raised $7.4M Seed round.
"""
    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.stdout = mock_stdout

    candidates = search_agent_reach_candidates(
        "AI agents for SMBs",
        runner=lambda *args, **kwargs: mock_process,
        limit=5,
    )

    assert len(candidates) == 2
    assert candidates[0].name == "Dock"
    assert candidates[0].website == "https://trydock.ai"
    assert candidates[0].batch == "Product Hunt Launch"
    assert candidates[0].is_hiring is True

    assert candidates[1].name == "SynthFlow"
    assert candidates[1].website == "https://synthflow.ai"


def test_search_agent_reach_candidates_error_handling() -> None:
    def failing_runner(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["mcporter"], timeout=30)

    assert search_agent_reach_candidates("test", runner=failing_runner) == []


def test_parse_url_seed_candidates() -> None:
    # Test list of URLs
    urls = [
        "https://trydock.ai",
        "https://gini.ai/app",
        "marker.ai",
        "# comment line",
    ]
    candidates = parse_url_seed_candidates(urls)
    assert len(candidates) == 3
    assert candidates[0].name == "Trydock"
    assert candidates[0].website == "https://trydock.ai"
    assert candidates[1].name == "Gini"
    assert candidates[2].name == "Marker"
    assert candidates[2].website == "https://marker.ai"

    # Test structured dicts
    dicts = [
        {
            "name": "Dock",
            "website": "https://trydock.ai",
            "one_liner": "Multiplayer workspace",
            "team_size": 3,
            "is_hiring": True,
        }
    ]
    cand_from_dicts = parse_url_seed_candidates(dicts)
    assert len(cand_from_dicts) == 1
    assert cand_from_dicts[0].name == "Dock"
    assert cand_from_dicts[0].team_size == 3
    assert cand_from_dicts[0].is_hiring is True


def test_deduplicate_and_merge_candidates() -> None:
    c1 = Candidate(
        slug="dock",
        name="Dock",
        website="https://trydock.ai",
        one_liner="Multiplayer agent workspace",
        description="Core product description",
        batch="Summer 2026",
        industry="B2B AI",
        tags=["YC", "B2B"],
        team_size=2,
        launched_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        is_hiring=False,
        source_url="https://ycombinator.com/companies/dock",
    )
    c2 = Candidate(
        slug="trydock",
        name="Dock AI",
        website="https://trydock.ai",
        one_liner="Autonomous agent workspace for SMB teams",
        description="Traction: Show HN 150 points. Actively hiring.",
        batch="Show HN",
        industry="AI",
        tags=["Show HN", "Hacker News"],
        team_size=None,
        launched_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        is_hiring=True,
        source_url="https://news.ycombinator.com/item?id=123",
    )

    merged = deduplicate_and_merge_candidates([c1, c2])
    assert len(merged) == 1
    result = merged[0]
    assert result.name in {"Dock", "Dock AI"}
    assert result.website == "https://trydock.ai"
    assert "Core product description" in result.description
    assert "Traction: Show HN" in result.description
    assert set(result.tags) == {"YC", "B2B", "Show HN", "Hacker News"}
    assert result.team_size == 2
    assert result.is_hiring is True
    assert result.batch == "Summer 2026"


def test_load_candidates_from_url_seed_file(tmp_path: Path) -> None:
    # Test JSON array of strings
    json_url_file = tmp_path / "urls.json"
    json_url_file.write_text(json.dumps(["https://trydock.ai", "https://gini.ai"]))
    cands1 = load_candidates(json_url_file, batch=None, lookback_days=30)
    assert len(cands1) == 2
    assert cands1[0].website == "https://trydock.ai"

    # Test plain text seed file
    txt_file = tmp_path / "seeds.txt"
    txt_file.write_text("https://trydock.ai\nhttps://gini.ai\n# comment\nhttps://marker.ai\n")
    cands2 = load_candidates(txt_file, batch=None, lookback_days=30)
    assert len(cands2) == 3


def test_discover_candidates_multi_source_orchestration() -> None:
    yc_records = [
        {
            "id": "yc-dock",
            "slug": "dock",
            "name": "Dock",
            "website": "https://trydock.ai",
            "one_liner": "Multiplayer agent workspace",
            "long_description": "YC company profile description",
            "batch": "Summer 2026",
            "status": "Active",
            "launched_at": int(datetime(2026, 8, 10, tzinfo=timezone.utc).timestamp()),
            "team_size": 2,
            "isHiring": False,
        }
    ]

    mock_hn_data = {
        "hits": [
            {
                "objectID": "999",
                "title": "Show HN: Gini – Autonomous AI CFO for SMBs",
                "url": "https://gini.ai",
                "author": "aditya",
                "points": 120,
                "num_comments": 45,
                "created_at": "2026-08-12T10:00:00Z",
                "story_text": "We are hiring engineers.",
            }
        ]
    }

    def hn_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_hn_data, request=request)

    client = httpx.Client(transport=httpx.MockTransport(hn_handler))

    mock_reach_stdout = """Title: Marker: Autonomous AI Code Review | Product Hunt
URL: https://www.producthunt.com/products/marker
Highlights: Marker AI (https://marker.ai) automatically reviews PRs. Raised $2M.
"""
    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.stdout = mock_reach_stdout

    cands = discover_candidates(
        topic="AI agents for SMBs",
        batch=None,
        lookback_days=30,
        client=client,
        yc_records=yc_records,
        runner=lambda *args, **kwargs: mock_process,
        limit=10,
    )

    assert len(cands) == 3
    domains = {normalize_domain(c.website) for c in cands}
    assert domains == {"trydock.ai", "gini.ai", "marker.ai"}
