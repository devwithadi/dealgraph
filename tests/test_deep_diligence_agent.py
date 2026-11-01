from __future__ import annotations

import subprocess
from datetime import datetime, timezone
import pytest

import httpx

from app.analysis.diligence import (
    DeepDiligenceAgent,
    DiligencePillar,
    DiligencePlan,
    DiligenceState,
    InformationGap,
    SearchQuery,
    evaluate_evidence_gaps,
    generate_diligence_plan,
    generate_followup_queries,
)
from app.analysis.diligence.tools.scraper import WebFetchTool
from app.analysis.diligence.agent import default_live_search
from app.domain.models import Candidate, Evidence
from app.domain.enums import CitationTag
from app.sourcing.policy import SourcePolicyError


@pytest.fixture
def mock_candidate() -> Candidate:
    return Candidate(
        slug="nexus-ai",
        name="Nexus AI",
        website="https://nexus.example.com",
        one_liner="Autonomous AI agent platform for enterprise workflows",
        description="Nexus AI provides autonomous agent systems for enterprise ERP and CRM orchestration.",
        batch="Summer 2026",
        industry="Enterprise Software",
        tags=["AI", "Enterprise", "Agents"],
        team_size=5,
        launched_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        is_hiring=True,
        source_url="https://api.ycombinator.com/v0.1/companies/nexus-ai",
    )


@pytest.fixture
def mock_initial_evidence() -> list[Evidence]:
    return [
        Evidence(
            id="ev-001",
            claim="YC Company Profile",
            excerpt="Nexus AI provides autonomous agent systems for enterprise ERP. Reported team size: 5.",
            source_url="https://api.ycombinator.com/v0.1/companies/nexus-ai",
            source_title="YC profile: Nexus AI",
            source_type="yc_directory",
            trust_tier="curated_directory",
            verification="third_party",
        )
    ]


def test_planner_generates_three_focused_queries(mock_candidate: Candidate) -> None:
    plan = generate_diligence_plan(mock_candidate, "Enterprise AI Agents")

    assert plan.candidate_slug == "nexus-ai"
    assert plan.candidate_name == "Nexus AI"
    assert plan.topic == "Enterprise AI Agents"
    assert len(plan.queries) == 3
    assert len(plan.focus_areas) == 3

    pillars = {q.pillar for q in plan.queries}
    expected_pillars = {
        DiligencePillar.COMMERCIAL_TAM.value,
        DiligencePillar.UNIT_ECONOMICS.value,
        DiligencePillar.TECH_IP.value,
    }
    assert pillars == expected_pillars
    queries = " ".join(q.query.lower() for q in plan.queries)
    assert "founder" in queries and "team" in queries
    assert "traction" in queries and "funding" in queries and "latest" in queries
    assert "competitor" in queries and "differentiation" in queries

    for q in plan.queries:
        assert "Nexus AI" in q.query
        assert q.hop == 1
        assert not q.executed
        assert len(q.rationale) > 0


def test_evaluator_identifies_and_resolves_gaps(mock_candidate: Candidate) -> None:
    # 1. With minimal evidence (only high-level YC profile without financial/tech/risk depth)
    minimal_ev = [
        Evidence(
            id="ev-001",
            claim="Company Profile",
            excerpt="Nexus AI builds software.",
            source_url="https://nexus.example.com",
            source_title="Nexus",
            source_type="web",
            trust_tier="open_web",
            verification="third_party",
        )
    ]
    gaps = evaluate_evidence_gaps(mock_candidate, minimal_ev, "Enterprise AI")
    assert len(gaps) == 4
    # All 4 pillars should have unresolved gaps with minimal evidence
    unresolved_pillars = {g.pillar for g in gaps if not g.resolved}
    assert len(unresolved_pillars) == 4

    # Follow-up queries generated for unresolved gaps
    followups = generate_followup_queries(mock_candidate, gaps, hop=2, topic="Enterprise AI")
    assert len(followups) == 4
    for q in followups:
        assert q.hop == 2
        assert "Nexus AI" in q.query

    pricing_heading_only = [
        Evidence(
            id="ev-001",
            claim="Company website",
            excerpt="[PRICING & TIERS]: Contact us to learn about the product.",
            source_url="https://nexus.example.com/pricing",
            source_title="Pricing",
            source_type="web_scraper",
            trust_tier="self_reported",
            verification="direct_scrape",
        )
    ]
    heading_gaps = evaluate_evidence_gaps(mock_candidate, pricing_heading_only)
    economics_gap = next(
        gap for gap in heading_gaps if gap.pillar == DiligencePillar.UNIT_ECONOMICS.value
    )
    assert economics_gap.resolved is False

    first_party_commercial = [
        Evidence(
            id="ev-001",
            claim="Customer traction",
            excerpt="We serve many enterprise customers in a growing market.",
            source_url="https://nexus.example.com/customers",
            source_title="Nexus customers",
            source_type="company_website",
            trust_tier="first_party",
            verification="direct_scrape",
            status=CitationTag.CLAIMED,
        )
    ]
    commercial_gap = next(
        gap
        for gap in evaluate_evidence_gaps(mock_candidate, first_party_commercial)
        if gap.pillar == DiligencePillar.COMMERCIAL_TAM.value
    )
    assert commercial_gap.resolved is False

    # 2. Comprehensive evidence resolving all pillars
    full_evidence = [
        Evidence(
            id="ev-001",
            claim="Commercial traction",
            excerpt="Nexus AI signed 12 enterprise customer contracts in the market expansion.",
            source_url="https://news.example/traction",
            source_title="Nexus Market Traction",
            source_type="deep_diligence",
            trust_tier="open_web",
            verification="multi_hop_search",
            status=CitationTag.TRUSTED,
        ),
        Evidence(
            id="ev-002",
            claim="Unit economics",
            excerpt="Nexus AI reached $2.5M ARR with strong subscription pricing tiers and 18 months runway.",
            source_url="https://news.example/financials",
            source_title="Nexus Financials",
            source_type="deep_diligence",
            trust_tier="open_web",
            verification="multi_hop_search",
            status=CitationTag.TRUSTED,
        ),
        Evidence(
            id="ev-003",
            claim="Tech moat",
            excerpt="Nexus AI uses proprietary agent architecture and benchmark models with technical patents.",
            source_url="https://news.example/tech",
            source_title="Nexus Architecture",
            source_type="deep_diligence",
            trust_tier="open_web",
            verification="multi_hop_search",
            status=CitationTag.TRUSTED,
        ),
        Evidence(
            id="ev-004",
            claim="Risk analysis",
            excerpt="Key risks include customer churn, compliance with GDPR regulations and API dependency.",
            source_url="https://news.example/risks",
            source_title="Nexus Risks",
            source_type="deep_diligence",
            trust_tier="open_web",
            verification="multi_hop_search",
            status=CitationTag.TRUSTED,
        ),
    ]
    resolved_gaps = evaluate_evidence_gaps(mock_candidate, full_evidence, "Enterprise AI")
    assert all(g.resolved for g in resolved_gaps)
    no_followups = generate_followup_queries(mock_candidate, resolved_gaps, hop=2)
    assert len(no_followups) == 0


def test_deep_diligence_agent_multi_hop_live_search_loop(
    mock_candidate: Candidate,
    mock_initial_evidence: list[Evidence],
) -> None:
    events: list[tuple[str, dict]] = []

    def callback(event: str, data: dict) -> None:
        events.append((event, data))

    # Mock search function that returns commercial & tech evidence in Hop 1,
    # and unit economics & risk evidence in Hop 2.
    def mock_search(cand: Candidate, query_item: SearchQuery, start_id: int) -> list[Evidence]:
        if query_item.pillar == DiligencePillar.COMMERCIAL_TAM.value:
            return [
                Evidence(
                    id=f"ev-{start_id:03d}",
                    claim="Market traction",
                    excerpt=f"{cand.name} signed enterprise market customers.",
                    source_url=f"https://news.example/commercial-{query_item.hop}",
                    source_title="Commercial Traction",
                    source_type="deep_diligence",
                    trust_tier="open_web",
                    verification="multi_hop_search",
                    status=CitationTag.TRUSTED,
                )
            ]
        elif query_item.pillar == DiligencePillar.TECH_IP.value:
            return [
                Evidence(
                    id=f"ev-{start_id:03d}",
                    claim="Tech architecture",
                    excerpt=f"{cand.name} proprietary model architecture and benchmarks.",
                    source_url=f"https://news.example/tech-{query_item.hop}",
                    source_title="Tech Specs",
                    source_type="deep_diligence",
                    trust_tier="open_web",
                    verification="multi_hop_search",
                    status=CitationTag.TRUSTED,
                )
            ]
        elif query_item.pillar == DiligencePillar.UNIT_ECONOMICS.value and query_item.hop >= 2:
            return [
                Evidence(
                    id=f"ev-{start_id:03d}",
                    claim="Pricing and revenue",
                    excerpt=f"{cand.name} pricing tiers and $1M ARR with funding.",
                    source_url=f"https://news.example/pricing-{query_item.hop}",
                    source_title="Pricing Details",
                    source_type="deep_diligence",
                    trust_tier="open_web",
                    verification="multi_hop_search",
                    status=CitationTag.TRUSTED,
                )
            ]
        elif query_item.pillar == DiligencePillar.RISK_ESG.value and query_item.hop >= 2:
            return [
                Evidence(
                    id=f"ev-{start_id:03d}",
                    claim="Compliance risk",
                    excerpt=f"{cand.name} addresses GDPR regulation and security risks.",
                    source_url=f"https://news.example/risks-{query_item.hop}",
                    source_title="Risk Assessment",
                    source_type="deep_diligence",
                    trust_tier="open_web",
                    verification="multi_hop_search",
                    status=CitationTag.TRUSTED,
                )
            ]
        return []

    mock_scraper = WebFetchTool(
        client=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(404, request=req))),
        url_validator=lambda u: u,
    )

    agent = DeepDiligenceAgent(
        max_hops=2,
        search_fn=mock_search,
        scraper_tool=mock_scraper,
        progress_callback=callback,
    )
    state = agent.run(mock_candidate, "Enterprise AI Agents", initial_evidence=mock_initial_evidence)

    assert state.is_complete
    assert state.current_hop == 2
    # Initial 1 + Hop 1 (2) + Hop 2 (2) = 5 evidence items
    assert len(state.evidence) == 5
    assert len(state.queries_executed) == 5  # 3 in hop 1 + 2 followups in hop 2

    event_names = [e[0] for e in events]
    assert "diligence_plan_generated" in event_names
    assert "diligence_scrape_start" in event_names
    assert "diligence_hop_start" in event_names
    assert "diligence_hop_complete" in event_names
    assert "diligence_all_gaps_resolved" in event_names


def test_default_live_search_subprocess_and_parsing(mock_candidate: Candidate) -> None:
    query_item = SearchQuery(
        query="Nexus AI pricing revenue",
        pillar=DiligencePillar.UNIT_ECONOMICS.value,
        hop=1,
    )

    stdout_data = (
        "Title: Nexus AI Pricing & Plans\n"
        "URL: https://nexus.example.com/pricing\n"
        "Highlights: Nexus AI offers enterprise pricing starting at $500/month.\n"
        "---\n"
        "Title: Invalid URL Result\n"
        "URL: http://127.0.0.1:8080/internal\n"
        "Highlights: Internal test\n"
        "---\n"
        "Title: TechCrunch Nexus Launch\n"
        "URL: https://techcrunch.com/nexus-launch\n"
        "Highlights: Nexus AI raised $3M in seed funding for agent automation.\n"
    )

    def mock_runner(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=stdout_data,
            stderr="",
        )

    results = default_live_search(
        mock_candidate,
        query_item,
        start_id=2,
        runner=mock_runner,
        resolver=lambda _host: ["93.184.216.34"],
    )
    assert len(results) == 2  # http://127.0.0.1 filtered by policy
    assert results[0].id == "ev-002"
    assert results[0].source_url == "https://nexus.example.com/pricing"
    assert results[1].id == "ev-003"
    assert results[1].source_url == "https://techcrunch.com/nexus-launch"


def test_default_live_search_error_handling(mock_candidate: Candidate) -> None:
    query_item = SearchQuery(
        query="Nexus AI pricing",
        pillar=DiligencePillar.UNIT_ECONOMICS.value,
        hop=1,
    )

    def failing_runner(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="mcporter", timeout=35)

    assert default_live_search(mock_candidate, query_item, start_id=1, runner=failing_runner) == []

    def error_runner(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="error")

    assert default_live_search(mock_candidate, query_item, start_id=1, runner=error_runner) == []


def test_rate_limit_is_safe_and_stops_repeated_search_calls(
    mock_candidate: Candidate,
    mock_initial_evidence: list[Evidence],
) -> None:
    calls = 0
    events: list[tuple[str, dict]] = []

    def rate_limited_runner(*args, **kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="HTTP 429 quota exhausted secret-provider-body",
        )

    query = SearchQuery(query="Nexus AI customers", pillar=DiligencePillar.COMMERCIAL_TAM.value)
    with pytest.raises(SourcePolicyError, match="rate limited"):
        default_live_search(mock_candidate, query, 2, runner=rate_limited_runner)

    calls = 0
    scraper = WebFetchTool(
        client=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(404, request=req))),
        url_validator=lambda url: url,
    )
    state = DeepDiligenceAgent(
        runner=rate_limited_runner,
        scraper_tool=scraper,
        progress_callback=lambda event, data: events.append((event, data)),
    ).run(mock_candidate, "Enterprise AI", initial_evidence=mock_initial_evidence)

    assert calls == 1
    availability_gap = next(gap for gap in state.gaps if gap.pillar == "Research availability")
    assert availability_gap.resolved is False
    assert availability_gap.severity == "high"
    event = next(data for name, data in events if name == "diligence_search_unavailable")
    assert event["status"] == "rate_limited"
    assert "secret-provider-body" not in str(event)


def test_is_allowed_url_edge_cases() -> None:
    from app.analysis.diligence.agent import _is_allowed_url

    assert not _is_allowed_url("https://example.com:notaport/test")
    assert not _is_allowed_url("https://pitchbook.com/profile")
    assert not _is_allowed_url("ftp://example.com/file")
    assert _is_allowed_url("https://techcrunch.com/article")


def test_agent_progress_callback_exception_absorption(mock_candidate: Candidate) -> None:
    def broken_callback(event: str, data: dict) -> None:
        raise RuntimeError("Callback crashed")

    agent = DeepDiligenceAgent(
        max_hops=1,
        search_fn=lambda *_args: [],
        scraper_tool=WebFetchTool(
            client=httpx.Client(
                transport=httpx.MockTransport(lambda req: httpx.Response(404, request=req))
            ),
            url_validator=lambda url: url,
        ),
        progress_callback=broken_callback,
    )
    # Should not raise exception
    state = agent.run(mock_candidate, "Enterprise AI")
    assert state.is_complete
