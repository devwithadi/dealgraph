from __future__ import annotations

import subprocess
from datetime import datetime, timezone
import pytest

import httpx

from app.analysis.diligence import (
    DeepDiligenceAgent,
    DiligenceEvaluation,
    DiligencePillar,
    GapSeverity,
    InformationGap,
    SearchQuery,
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


def mock_evaluation(
    candidate: Candidate,
    evidence: list[Evidence],
    topic: str,
    hop: int,
) -> DiligenceEvaluation:
    text = " ".join(f"{item.claim} {item.excerpt} {item.source_title}" for item in evidence).lower()
    signals = {
        DiligencePillar.COMMERCIAL_TAM: ("customer", "market", "commercial", "traction"),
        DiligencePillar.UNIT_ECONOMICS: ("$", "arr", "revenue", "pricing", "funding"),
        DiligencePillar.TECH_IP: ("architecture", "patent", "proprietary", "benchmark"),
        DiligencePillar.RISK_ESG: ("risk", "churn", "compliance", "gdpr"),
    }
    gaps: list[InformationGap] = []
    queries: list[SearchQuery] = []
    for pillar, markers in signals.items():
        matched = next(
            (
                item
                for item in evidence
                if any(marker in f"{item.claim} {item.excerpt} {item.source_title}".lower() for marker in markers)
                and (
                    pillar is not DiligencePillar.COMMERCIAL_TAM
                    or item.status in {CitationTag.TRUSTED, CitationTag.VERIFIED}
                )
                and not (pillar is DiligencePillar.UNIT_ECONOMICS and "contact us" in text and not any(char.isdigit() for char in text))
            ),
            None,
        )
        resolved = matched is not None
        gaps.append(
            InformationGap(
                pillar=pillar,
                description=f"{pillar.value} {'covered' if resolved else 'unresolved'}",
                severity=GapSeverity.LOW if resolved else GapSeverity.HIGH,
                resolved=resolved,
                rationale="Test evaluation",
                resolved_by_evidence_id=matched.id if matched else None,
            )
        )
        if not resolved:
            queries.append(
                SearchQuery(
                    query=f"{candidate.name} {pillar.value} evidence",
                    pillar=pillar,
                    rationale="Resolve test gap",
                    hop=hop,
                )
            )
    return DiligenceEvaluation(gaps=gaps, followup_queries=queries)


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
        if query_item.pillar is DiligencePillar.COMMERCIAL_TAM:
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
        elif query_item.pillar is DiligencePillar.TECH_IP:
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
        elif query_item.pillar is DiligencePillar.UNIT_ECONOMICS and query_item.hop >= 2:
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
        elif query_item.pillar is DiligencePillar.RISK_ESG and query_item.hop >= 2:
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
        evaluation_fn=mock_evaluation,
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
    assert len(state.queries_executed) == 6  # 4 in hop 1 + 2 followups in hop 2

    event_names = [e[0] for e in events]
    assert "diligence_plan_generated" in event_names
    assert "diligence_scrape_start" in event_names
    assert "diligence_hop_start" in event_names
    assert "diligence_hop_complete" in event_names
    assert "diligence_all_gaps_resolved" in event_names


def test_default_live_search_subprocess_and_parsing(mock_candidate: Candidate) -> None:
    query_item = SearchQuery(
        query="Nexus AI pricing revenue",
        pillar=DiligencePillar.UNIT_ECONOMICS,
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
        pillar=DiligencePillar.UNIT_ECONOMICS,
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

    query = SearchQuery(query="Nexus AI customers", pillar=DiligencePillar.COMMERCIAL_TAM)
    with pytest.raises(SourcePolicyError, match="rate limited"):
        default_live_search(mock_candidate, query, 2, runner=rate_limited_runner)

    calls = 0
    scraper = WebFetchTool(
        client=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(404, request=req))),
        url_validator=lambda url: url,
    )
    state = DeepDiligenceAgent(
        evaluation_fn=mock_evaluation,
        runner=rate_limited_runner,
        scraper_tool=scraper,
        progress_callback=lambda event, data: events.append((event, data)),
    ).run(mock_candidate, "Enterprise AI", initial_evidence=mock_initial_evidence)

    assert calls == 1
    availability_gap = next(gap for gap in state.gaps if gap.pillar is DiligencePillar.RESEARCH_AVAILABILITY)
    assert availability_gap.resolved is False
    assert availability_gap.severity is GapSeverity.HIGH
    event = next(data for name, data in events if name == "diligence_search_unavailable")
    assert event["status"] == "rate_limited"
    assert "secret-provider-body" not in str(event)


def test_rate_limit_keeps_evidence_collected_earlier_in_the_hop(
    mock_candidate: Candidate,
    mock_initial_evidence: list[Evidence],
) -> None:
    calls = 0

    def partial_search(cand: Candidate, query: SearchQuery, start_id: int) -> list[Evidence]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return [
                Evidence(
                    id=f"ev-{start_id:03d}",
                    claim="Independent customer traction",
                    excerpt=f"{cand.name} signed 12 enterprise customers.",
                    source_url="https://news.example/nexus-traction",
                    source_title="Independent traction report",
                    source_type="deep_diligence_search",
                    trust_tier="open_web",
                    verification="multi_hop_search",
                    status=CitationTag.TRUSTED,
                )
            ]
        raise SourcePolicyError("Independent search rate limited")

    scraper = WebFetchTool(
        client=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(404, request=req))),
        url_validator=lambda url: url,
    )
    state = DeepDiligenceAgent(
        evaluation_fn=mock_evaluation,
        search_fn=partial_search,
        scraper_tool=scraper,
    ).run(
        mock_candidate,
        "Enterprise AI",
        initial_evidence=mock_initial_evidence,
    )

    assert calls == 2
    assert any(item.source_url == "https://news.example/nexus-traction" for item in state.evidence)
    commercial_gap = next(gap for gap in state.gaps if gap.pillar is DiligencePillar.COMMERCIAL_TAM)
    assert commercial_gap.resolved is True


def test_is_allowed_url_edge_cases() -> None:
    from app.analysis.diligence.agent import _is_allowed_url

    assert not _is_allowed_url("https://example.com:notaport/test")
    assert _is_allowed_url("https://pitchbook.com/profile")
    assert not _is_allowed_url("ftp://example.com/file")
    assert _is_allowed_url("https://techcrunch.com/article")


def test_agent_progress_callback_exception_absorption(mock_candidate: Candidate) -> None:
    def broken_callback(event: str, data: dict) -> None:
        raise RuntimeError("Callback crashed")

    agent = DeepDiligenceAgent(
        evaluation_fn=mock_evaluation,
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
