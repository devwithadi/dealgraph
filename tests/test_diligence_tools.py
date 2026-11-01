from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
import httpx
import pytest

from app.analysis.diligence.models import DiligencePillar, SearchQuery
from app.analysis.diligence.tools.ranker import EvidenceRanker, normalize_url
from app.analysis.diligence.tools.scraper import ScraperTool, WebFetchTool, extract_html_text
from app.analysis.diligence.tools.search import SearchTool, _parse_search_output, _resolve_status_for_url, is_allowed_url
from app.domain.enums import CitationTag
from app.domain.models import Candidate, Evidence
from app.sourcing.policy import SourcePolicyError


@pytest.fixture
def test_candidate() -> Candidate:
    return Candidate(
        slug="strata-data",
        name="Strata Data",
        website="https://stratadata.example.com",
        one_liner="Automated data lake indexing and semantic cataloging",
        description="Strata Data provides real-time vector and relational indexing for massive enterprise data lakes.",
        batch="Winter 2026",
        industry="Data Infrastructure",
        tags=["Data", "AI", "Enterprise"],
        team_size=6,
        launched_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
        is_hiring=True,
        source_url="https://api.ycombinator.com/v0.1/companies/strata-data",
    )


def test_search_tool_url_allowlist_and_status_resolution() -> None:
    assert is_allowed_url("https://techcrunch.com/article") is True
    assert is_allowed_url("https://sec.gov/edgar/data") is True
    assert is_allowed_url("http://github.com/stratadata") is True

    # Blocked hosts
    assert is_allowed_url("https://pitchbook.com/profiles/123") is False
    assert is_allowed_url("https://www.linkedin.com/in/founder") is False
    assert is_allowed_url("https://crunchbase.com/org/strata") is False

    # Status resolution
    assert _resolve_status_for_url("https://sec.gov/filing") == CitationTag.VERIFIED
    assert _resolve_status_for_url("https://www.uspto.gov/patents") == CitationTag.VERIFIED
    assert _resolve_status_for_url("https://techcrunch.com/2026/strata") == CitationTag.TRUSTED


def test_search_tool_parse_output(test_candidate: Candidate) -> None:
    sample_stdout = """Title: Strata Data Raises $4M Seed
URL: https://techcrunch.com/2026/02/strata-data-seed
Highlights: Strata Data raised a $4M seed round to index enterprise data lakes.

----------------------------------------
Title: Strata SEC Form D
URL: https://sec.gov/edgar/data/strata
Highlights: Notice of Exempt Offering of Securities filed on 2026-02-15.

----------------------------------------
Title: Invalid LinkedIn Profile
URL: https://linkedin.com/company/stratadata
Highlights: LinkedIn employee directory.
"""
    query = SearchQuery(
        query="Strata Data funding round",
        pillar=DiligencePillar.UNIT_ECONOMICS.value,
        hop=1,
    )

    ev_list = _parse_search_output(sample_stdout, query, start_id=1)
    assert len(ev_list) == 2  # LinkedIn blocked

    assert ev_list[0].id == "ev-001"
    assert ev_list[0].status == CitationTag.TRUSTED
    assert "Strata Data Raises $4M Seed" in ev_list[0].source_title
    assert "techcrunch.com" in ev_list[0].source_url

    assert ev_list[1].id == "ev-002"
    assert ev_list[1].status == CitationTag.VERIFIED
    assert "sec.gov" in ev_list[1].source_url


def test_search_tool_execution_with_custom_fn(test_candidate: Candidate) -> None:
    query = SearchQuery(query="test query", pillar=DiligencePillar.TECH_IP.value)

    def custom_fn(candidate, q, start_id):
        return [
            Evidence(
                id=f"ev-{start_id:03d}",
                claim="Custom search result",
                excerpt="Proprietary index architecture.",
                source_url="https://docs.stratadata.example.com",
                source_title="Technical Whitepaper",
                source_type="deep_diligence_search",
                trust_tier="multi_hop_web",
                verification="multi_hop_search",
                status=CitationTag.TRUSTED,
            )
        ]

    tool = SearchTool(custom_search_fn=custom_fn)
    results = tool.search(test_candidate, query, start_id=5)
    assert len(results) == 1
    assert results[0].id == "ev-005"
    assert results[0].status == CitationTag.TRUSTED


def test_search_tool_handles_subprocess_failure(test_candidate: Candidate) -> None:
    query = SearchQuery(query="fail query", pillar=DiligencePillar.RISK_ESG.value)

    def failing_runner(*args, **kwargs):
        raise OSError("Subprocess execution failed")

    tool = SearchTool(runner=failing_runner)
    results = tool.search(test_candidate, query, start_id=1)
    assert results == []


def test_scraper_extract_html_text() -> None:
    html_sample = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Strata Data &mdash; AI Lakehouse</title>
        <script>var x = 123;</script>
        <style>.hide { display: none; }</style>
    </head>
    <body>
        <h1>Next-Gen Data Lake Indexing</h1>
        <p>Strata delivers sub-millisecond semantic search across petabyte-scale lakes.</p>
    </body>
    </html>
    """
    title, text = extract_html_text(html_sample)
    assert "Strata Data — AI Lakehouse" in title
    assert "Next-Gen Data Lake Indexing" in text
    assert "sub-millisecond semantic search" in text
    assert "var x = 123" not in text


def test_scraper_tool_fetches_and_creates_evidence(test_candidate: Candidate) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        content = "<html><head><title>Strata Product</title></head><body>Enterprise data lake indexing.</body></html>"
        return httpx.Response(200, text=content, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = ScraperTool(client=client, url_validator=lambda u: u)

    ev = scraper.scrape_to_evidence("https://stratadata.example.com/product", "ev-010")
    assert ev.id == "ev-010"
    assert ev.status == CitationTag.CLAIMED
    assert ev.source_type == "web_scraper"
    assert "Strata Product" in ev.source_title
    assert "Enterprise data lake indexing" in ev.excerpt


def test_scraper_tool_assigns_verified_status_for_canonical_registry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        content = "<html><head><title>SEC Edgar Record</title></head><body>Official company registration.</body></html>"
        return httpx.Response(200, text=content, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = WebFetchTool(client=client, url_validator=lambda u: u)

    ev = scraper.scrape_to_evidence("https://sec.gov/edgar/data/123", "ev-020")
    assert ev.id == "ev-020"
    assert ev.status == CitationTag.VERIFIED
    assert ev.trust_tier == "canonical_registry"


def test_scraper_tool_raises_source_policy_error_on_blocked_url() -> None:
    scraper = WebFetchTool()
    with pytest.raises(SourcePolicyError):
        scraper.scrape_to_evidence("https://pitchbook.com/company/123", "ev-030")


def test_scraper_tool_scrape_candidate_pages(test_candidate: Candidate) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "pricing" in url_str:
            content = "<html><head><title>Strata Pricing</title></head><body>Tier 1 starts at $100/mo. Enterprise tier is custom.</body></html>"
        elif "product" in url_str:
            content = "<html><head><title>Strata Product</title></head><body>Vector indexing engine with sub-second queries.</body></html>"
        elif "security" in url_str:
            content = "<html><head><title>Strata Security</title></head><body>SOC2 Type II certified and GDPR compliant data pipeline.</body></html>"
        else:
            content = "<html><head><title>Strata Data Home</title></head><body>Enterprise data lake indexing and semantic catalog.</body></html>"
        return httpx.Response(200, text=content, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = WebFetchTool(client=client, url_validator=lambda u: u)

    scraped_events: list[tuple[str, str, int]] = []
    evidence_list = scraper.scrape_candidate_pages(
        test_candidate,
        start_id=1,
        on_page_scraped=lambda subpage, title, length: scraped_events.append((subpage, title, length)),
    )

    assert len(evidence_list) == 6
    assert all(e.source_type == "web_scraper" for e in evidence_list)
    assert all(e.status == CitationTag.CLAIMED for e in evidence_list)
    assert len(scraped_events) == 6

    # Test with empty website
    empty_cand = Candidate(
        slug="empty",
        name="Empty",
        website="",
        one_liner="Empty",
        description="",
        batch="",
        industry="",
        tags=[],
        team_size=1,
        launched_at=datetime.now(timezone.utc),
        is_hiring=False,
        source_url="https://api.ycombinator.com/v0.1/companies/empty",
    )
    assert scraper.scrape_candidate_pages(empty_cand) == []


def test_evidence_ranker_deduplication_and_tagging() -> None:
    ranker = EvidenceRanker()

    ev1 = Evidence(
        id="ev-001",
        claim="YC Profile",
        excerpt="Strata Data provides real-time vector and relational indexing for massive enterprise data lakes.",
        source_url="https://ycombinator.com/companies/strata-data",
        source_title="YC Directory",
        source_type="yc_directory",
        trust_tier="curated_directory",
        verification="third_party",
    )
    # Duplicate by URL (with trailing slash)
    ev2 = Evidence(
        id="ev-002",
        claim="YC Duplicate",
        excerpt="Strata Data provides real-time vector and relational indexing for massive enterprise data lakes.",
        source_url="https://ycombinator.com/companies/strata-data/",
        source_title="YC Directory Duplicate",
        source_type="yc_directory",
        trust_tier="curated_directory",
        verification="third_party",
    )
    # SEC registry evidence
    ev3 = Evidence(
        id="ev-003",
        claim="SEC Filing",
        excerpt="Notice of sales of securities $4,000,000.",
        source_url="https://sec.gov/edgar/strata",
        source_title="SEC EDGAR",
        source_type="deep_diligence_search",
        trust_tier="multi_hop_web",
        verification="multi_hop_search",
    )
    # Founder self-reported page
    ev4 = Evidence(
        id="ev-004",
        claim="Website Pricing",
        excerpt="Enterprise pricing tier starts at $3,000/mo.",
        source_url="https://stratadata.example.com/pricing",
        source_title="Pricing Page",
        source_type="web_scraper",
        trust_tier="self_reported",
        verification="direct_scrape",
    )

    deduped = ranker.deduplicate([ev1, ev2, ev3, ev4])
    assert len(deduped) == 3  # ev2 deduplicated

    ranked = ranker.rank_and_reorder([ev1, ev2, ev3, ev4], topic="Enterprise Data Lake")
    assert len(ranked) == 3
    # Sequential IDs
    assert [r.id for r in ranked] == ["ev-001", "ev-002", "ev-003"]
    # Tag priorities: VERIFIED first, then TRUSTED/CLAIMED
    assert ranked[0].status == CitationTag.VERIFIED
    assert ranked[1].status == CitationTag.VERIFIED
    assert ranked[2].status == CitationTag.CLAIMED


def test_normalize_url_helper() -> None:
    assert normalize_url("https://Example.COM/path/to/page/") == "https://example.com/path/to/page"
    assert normalize_url("http://example.com:80/test?q=1#frag") == "http://example.com/test?q=1"
