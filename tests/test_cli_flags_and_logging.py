from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.cli.main import build_parser, main
from app.cli.reporter import ConsoleReporter, FinalistReportItem
from app.domain.enums import AIProvider, AnalysisMode, Recommendation
from app.domain.models import Analysis, Candidate, Evidence, Financials, RunSummary, ScreeningDecision
from app.pipeline.service import Pipeline, _safe_stage_error


NOW = datetime(2026, 8, 24, tzinfo=timezone.utc)


def _summary(tmp_path: Path, *, failed: int = 0) -> RunSummary:
    return RunSummary(
        run_id="run-cli-test",
        request_id="req-cli-test",
        output=str(tmp_path),
        candidates=10,
        screened=10,
        finalists=2,
        selected=2,
        succeeded=2 - failed,
        failed=failed,
    )


def test_cli_parser_model_flags() -> None:
    parser = build_parser()

    # Generic --model flag
    args1 = parser.parse_args(["run", "--topic", "AI", "--model", "nova-pro"])
    assert args1.model == "nova-pro"
    assert args1.screening_model is None
    assert args1.synthesis_model is None

    # Specific --screening-model and --synthesis-model flags
    args2 = parser.parse_args([
        "run",
        "--topic", "AI",
        "--model", "nova-pro",
        "--screening-model", "nova-micro",
        "--synthesis-model", "claude-3.5-sonnet",
    ])
    assert args2.model == "nova-pro"
    assert args2.screening_model == "nova-micro"
    assert args2.synthesis_model == "claude-3.5-sonnet"


def test_cli_main_passes_resolved_model_arguments(monkeypatch, tmp_path: Path) -> None:
    captured_kwargs: dict = {}

    def mock_run(self, **kwargs):
        captured_kwargs.update(kwargs)
        return _summary(tmp_path)

    monkeypatch.setattr("app.cli.main.new_request_id", lambda: "req-test")
    monkeypatch.setattr("app.cli.main.Pipeline.run", mock_run)

    # 1. When --model is supplied alone, both screening and synthesis use it
    main(["run", "--topic", "AI", "--model", "nova-pro", "--json"])
    assert captured_kwargs["screening_model"] == "nova-pro"
    assert captured_kwargs["synthesis_model"] == "nova-pro"

    # 2. When specific flags override --model
    captured_kwargs.clear()
    main([
        "run",
        "--topic", "AI",
        "--model", "nova-pro",
        "--screening-model", "nova-micro",
        "--synthesis-model", "claude-3.5-sonnet",
        "--json",
    ])
    assert captured_kwargs["screening_model"] == "nova-micro"
    assert captured_kwargs["synthesis_model"] == "claude-3.5-sonnet"


def test_console_reporter_output_formatting(capsys, tmp_path: Path) -> None:
    reporter = ConsoleReporter()

    # Header
    reporter("header", {
        "topic": "AI agents for SMBs",
        "lookback_days": 30,
        "cutoff": "2026-07-25T00:00:00+00:00",
        "provider": AIProvider.BEDROCK,
        "screening_model": "amazon.nova-micro-v1:0",
        "synthesis_model": "amazon.nova-lite-v1:0",
        "output": str(tmp_path),
    })

    # Sourcing
    reporter("sourcing_start", {"source": "https://api.ycombinator.com/v0.1/companies"})
    reporter("sourcing_complete", {"count": 2, "lookback_days": 30, "source": "https://api.ycombinator.com"})

    # Screening
    reporter("screening_start", {"total": 2, "batch_size": 20})
    reporter("screening_batch", {
        "batch_number": 1,
        "total_batches": 1,
        "start_index": 1,
        "end_index": 2,
        "decisions": [
            {
                "slug": "agentflow",
                "name": "AgentFlow",
                "fit_score": 85.0,
                "advance": True,
                "rationale": "High thesis alignment with SMB workflows",
            },
            {
                "slug": "petshop",
                "name": "PetShop",
                "fit_score": 15.0,
                "advance": False,
                "rationale": "B2C retail outside thesis scope",
            },
        ],
    })
    reporter("screening_complete", {"advancing": 1, "total": 2})

    # Diligence
    reporter("diligence_start", {"total": 1})
    reporter("finalist_start", {"index": 1, "total": 1, "name": "AgentFlow", "slug": "agentflow"})
    reporter("finalist_evidence", {"name": "AgentFlow", "slug": "agentflow", "count": 3, "yc_count": 1, "reach_count": 2})
    reporter("finalist_synthesis_start", {"name": "AgentFlow", "slug": "agentflow", "model": "amazon.nova-lite-v1:0"})
    reporter("finalist_success", {
        "name": "AgentFlow",
        "slug": "agentflow",
        "decision": "Take a meeting",
        "score": 88.0,
        "confidence": 0.85,
        "pdf_memo_path": str(tmp_path / "agentflow.pdf"),
    })

    # Summary table
    reporter("summary_table", {})

    output = capsys.readouterr().out
    assert "DealGraph Pipeline Run" in output
    assert "Topic: AI agents for SMBs" in output
    assert "Provider: bedrock" in output
    assert "Screening Model: amazon.nova-micro-v1:0" in output
    assert "[Sourcing] Sourcing candidates from" in output
    assert "[Sourcing] Sourced 2 candidate(s)" in output
    assert "[Screening] Evaluating 2 candidates" in output
    assert "[+] AgentFlow (Fit: 85.0/100 | ADVANCE) - High thesis alignment" in output
    assert "[-] PetShop (Fit: 15.0/100 | PASS) - B2C retail outside thesis scope" in output
    assert "[Screening] Screening complete: 1/2 candidates advancing to diligence." in output
    assert "[Diligence & Synthesis] Processing 1 finalists..." in output
    assert "[1/1] AgentFlow (slug: agentflow)" in output
    assert "- Evidence: Found 3 records (1 YC, 2 Agent Reach)." in output
    assert "- Synthesis: Generating investment memo with amazon.nova-lite-v1:0..." in output
    assert "- Result: Decision: Take a meeting | Score: 88.0/100 | Confidence: 0.85" in output
    assert "Finalist Summary" in output
    assert "AgentFlow" in output
    assert "Take a meeting" in output


def test_console_reporter_handles_finalist_failure(capsys) -> None:
    reporter = ConsoleReporter()
    reporter("finalist_start", {"index": 1, "total": 1, "name": "BrokenCo", "slug": "brokenco"})
    reporter("finalist_failure", {"name": "BrokenCo", "slug": "brokenco", "error": "ValueError: Invalid synthesis"})
    reporter("summary_table", {})

    output = capsys.readouterr().out
    assert "[1/1] BrokenCo" in output
    assert "- Failed: ValueError: Invalid synthesis" in output
    assert "BrokenCo" in output
    assert "Failed" in output


def test_console_reporter_empty_summary_table(capsys) -> None:
    reporter = ConsoleReporter()
    reporter("summary_table", {})
    output = capsys.readouterr().out
    assert "No finalists advanced to diligence." in output


def test_safe_stage_error_preserves_meaningful_messages() -> None:
    val_err = ValueError("synthesis citations missing")
    assert _safe_stage_error(val_err, "finalist") == "ValueError: synthesis citations missing"

    runtime_err = RuntimeError("Bedrock Converse API rate limit exceeded")
    assert _safe_stage_error(runtime_err, "screening") == "RuntimeError: Bedrock Converse API rate limit exceeded"

    empty_err = Exception("")
    assert _safe_stage_error(empty_err, "finalist") == "Finalist failed"


def test_pipeline_run_with_progress_callback_and_model_overrides(tmp_path: Path, monkeypatch) -> None:
    candidate_record = {
        "id": "agentdesk",
        "slug": "agentdesk",
        "name": "AgentDesk",
        "website": "https://agentdesk.example",
        "one_liner": "AI agents for SMB customer support",
        "long_description": "Platform description",
        "batch": "Summer 2026",
        "status": "Active",
        "launched_at": int(NOW.timestamp()),
    }
    source = tmp_path / "yc.json"
    source.write_text(json.dumps([candidate_record]), encoding="utf-8")

    monkeypatch.setattr(
        "app.pipeline.service.agent_reach_evidence",
        lambda candidate, topic, start: [
            Evidence(
                id="ev-002",
                claim="Agent Reach result",
                excerpt="AgentDesk launched customer pilot.",
                source_url="https://news.example/agentdesk",
                source_title="Pilot News",
                source_type="agent_reach",
                trust_tier="open_web",
                verification="third_party_search",
            )
        ],
    )

    models_called: list[str] = []

    class MockBedrockClient:
        def converse(self, **kwargs):
            models_called.append(kwargs["modelId"])
            stage = kwargs["requestMetadata"]["stage"]
            if stage == "screening":
                payload = {
                    "decisions": [
                        {
                            "slug": "agentdesk",
                            "advance": True,
                            "fit_score": 92.0,
                            "rationale": "High thesis fit",
                        }
                    ]
                }
            else:
                payload = {
                    "summary": "AgentDesk provides SMB agent automation. [ev-001]",
                    "team": "Unknown",
                    "product": "AgentDesk support automation platform. [ev-001]",
                    "market": "SMB customer support market. [ev-002]",
                    "why_now": "Rapid AI adoption. [ev-001]",
                    "risks": ["Retention is not yet proven. [ev-002]"],
                    "open_questions": ["What is SMB churn?"],
                    "changes_mind": ["Verified retention metrics", "Customer reference calls"],
                    "score": 90.0,
                    "confidence": 0.85,
                    "recommendation": "Take a meeting",
                    "citations": ["ev-001", "ev-002"],
                }
            return {"output": {"message": {"content": [{"text": json.dumps(payload)}]}}}

    events_received: list[tuple[str, dict]] = []

    def callback(event: str, data: dict) -> None:
        events_received.append((event, data))

    pipeline = Pipeline(bedrock_client=MockBedrockClient())
    result = pipeline.run(
        topic="AI agents for SMBs",
        batch=None,
        limit=None,
        output=tmp_path / "run",
        source_file=source,
        provider=AIProvider.BEDROCK,
        screening_model="amazon.nova-micro-v1:0",
        synthesis_model="us.meta.llama3-3-70b-instruct-v1:0",
        progress_callback=callback,
        now=NOW,
    )

    assert result.succeeded == 1
    assert result.failed == 0
    # Model IDs used directly
    assert models_called == ["amazon.nova-micro-v1:0", "us.meta.llama3-3-70b-instruct-v1:0"]
    assert (tmp_path / "run" / "agentdesk.pdf").exists()

    # Header event contains configured models
    header_data = events_received[0][1]
    assert header_data["screening_model"] == "amazon.nova-micro-v1:0"
    assert header_data["synthesis_model"] == "us.meta.llama3-3-70b-instruct-v1:0"

    # Events emitted in sequence
    event_names = [name for name, _ in events_received]
    assert event_names == [
        "header",
        "sourcing_start",
        "sourcing_complete",
        "screening_start",
        "screening_batch",
        "screening_complete",
        "diligence_start",
        "finalist_start",
        "finalist_evidence",
        "finalist_synthesis_start",
        "finalist_success",
        "summary_table",
    ]


def test_cli_parser_deep_diligence_and_provider_flags() -> None:
    parser = build_parser()

    # Test all AIProvider choices
    for prov in AIProvider:
        args = parser.parse_args(["run", "--topic", "AI", "--provider", prov.value])
        assert args.provider == prov

    # Test deep diligence default and flags
    args_default = parser.parse_args(["run", "--topic", "AI"])
    assert args_default.deep_diligence is True

    args_opt_out = parser.parse_args(["run", "--topic", "AI", "--no-deep-diligence"])
    assert args_opt_out.deep_diligence is False

    args_diligence = parser.parse_args([
        "run",
        "--topic", "AI",
        "--deep-diligence",
        "--max-hops", "3",
    ])
    assert args_diligence.deep_diligence is True
    assert args_diligence.max_hops == 3


def test_cli_main_passes_deep_diligence_arguments(monkeypatch, tmp_path: Path) -> None:
    captured_kwargs: dict = {}

    def mock_run(self, **kwargs):
        captured_kwargs.update(kwargs)
        return _summary(tmp_path)

    monkeypatch.setattr("app.cli.main.new_request_id", lambda: "req-test")
    monkeypatch.setattr("app.cli.main.Pipeline.run", mock_run)

    main([
        "run",
        "--topic", "AI agents",
        "--provider", "openrouter",
        "--deep-diligence",
        "--max-hops", "3",
        "--json",
    ])
    assert captured_kwargs["deep_diligence"] is True
    assert captured_kwargs["max_hops"] == 3
    assert captured_kwargs["provider"] == AIProvider.OPENROUTER


def test_console_reporter_deep_diligence_events(capsys) -> None:
    reporter = ConsoleReporter()

    reporter("diligence_plan_generated", {
        "candidate": "Nexus AI",
        "slug": "nexus-ai",
        "focus_areas": ["Commercial", "Unit Economics", "Tech", "Risk"],
        "queries_count": 4,
    })
    reporter("diligence_hop_start", {
        "candidate": "Nexus AI",
        "slug": "nexus-ai",
        "hop": 1,
        "max_hops": 2,
        "queries": ["Nexus AI market traction", "Nexus AI unit economics"],
        "pillars": ["Commercial / TAM", "Unit Economics"],
    })
    reporter("diligence_hop_complete", {
        "candidate": "Nexus AI",
        "slug": "nexus-ai",
        "hop": 1,
        "new_evidence_count": 2,
        "total_evidence_count": 3,
        "resolved_gaps": 2,
        "unresolved_gaps": 2,
    })
    reporter("diligence_all_gaps_resolved", {
        "candidate": "Nexus AI",
        "hop": 2,
    })
    reporter("diligence_scrape_start", {
        "candidate": "Nexus AI",
        "slug": "nexus-ai",
        "website": "https://nexus.example.com",
        "subpages": ["/", "/pricing", "/product"],
    })
    reporter("diligence_scrape_page", {
        "candidate": "Nexus AI",
        "slug": "nexus-ai",
        "subpage": "/pricing",
        "title": "Nexus Pricing",
        "length": 450,
    })
    reporter("diligence_scrape_complete", {
        "candidate": "Nexus AI",
        "slug": "nexus-ai",
        "scraped_count": 3,
        "total_evidence_count": 4,
    })
    reporter("diligence_query_start", {
        "candidate": "Nexus AI",
        "slug": "nexus-ai",
        "query": "Nexus AI pricing tiers",
        "pillar": "Unit Economics",
        "hop": 1,
    })
    reporter("diligence_evidence_collected", {
        "candidate": "Nexus AI",
        "id": "ev-005",
        "title": "Nexus Pricing Page",
        "url": "https://nexus.example.com/pricing",
        "pillar": "Unit Economics",
        "status": "claimed",
    })
    reporter("diligence_offline_complete", {
        "candidate": "Nexus AI",
        "slug": "nexus-ai",
        "evidence_count": 1,
        "gaps_count": 4,
    })
    reporter("finalist_success", {
        "name": "Nexus AI",
        "slug": "nexus-ai",
        "decision": "Take a meeting",
        "score": 88.5,
        "confidence": 0.82,
        "pdf_memo_path": "/tmp/results/nexus-ai.pdf",
    })
    reporter("summary_table", {})

    output = capsys.readouterr().out
    assert "Diligence Plan: Generated 4 research queries across 4 pillars for Nexus AI." in output
    assert "Diligence Scraping: Scraping candidate website https://nexus.example.com" in output
    assert "Scraped [/pricing]: Nexus Pricing (450 chars)" in output
    assert "Direct scraping complete: 3 subpage(s) captured" in output
    assert "Diligence [Hop 1/2]: Executing 2 research queries" in output
    assert "Search [Unit Economics]: Nexus AI pricing tiers" in output
    assert "[ev-005] [claimed] Nexus Pricing Page" in output
    assert "Diligence [Hop 1 Complete]: +2 new evidence (3 total) | Gaps: 2 resolved, 2 pending" in output
    assert "All 4-pillar information gaps resolved for Nexus AI in hop 2." in output
    assert "Diligence (Offline): Evaluated 1 local evidence items for Nexus AI (4 gaps)." in output
    assert "PDF Memo:     /tmp/results/nexus-ai.pdf" in output
    assert "open /tmp/results/nexus-ai.pdf" in output


def test_pipeline_run_with_deep_diligence_mode(tmp_path: Path, monkeypatch) -> None:
    candidate_record = {
        "id": "agentdesk",
        "slug": "agentdesk",
        "name": "AgentDesk",
        "website": "https://agentdesk.example",
        "one_liner": "AI agents for SMB customer support",
        "long_description": "Platform description",
        "batch": "Summer 2026",
        "status": "Active",
        "launched_at": int(NOW.timestamp()),
    }
    source = tmp_path / "yc.json"
    source.write_text(json.dumps([candidate_record]), encoding="utf-8")

    # Mock search function inside deep diligence agent
    monkeypatch.setattr(
        "app.analysis.diligence.agent.default_live_search",
        lambda candidate, query_item, start_id, runner=None: [
            Evidence(
                id=f"ev-{start_id:03d}",
                claim=f"Search evidence for {query_item.pillar}",
                excerpt=f"Verified data for {candidate.name} in {query_item.pillar}.",
                source_url=f"https://news.example/{candidate.slug}-{query_item.hop}-{start_id}",
                source_title=f"News on {query_item.pillar}",
                source_type="deep_diligence",
                trust_tier="open_web",
                verification="multi_hop_search",
            )
        ],
    )

    class MockBedrockClient:
        def converse(self, **kwargs):
            stage = kwargs["requestMetadata"]["stage"]
            if stage == "screening":
                payload = {
                    "decisions": [
                        {
                            "slug": "agentdesk",
                            "advance": True,
                            "fit_score": 92.0,
                            "rationale": "High thesis fit",
                        }
                    ]
                }
            else:
                payload = {
                    "summary": "AgentDesk provides SMB agent automation. [ev-001]",
                    "team": "Unknown",
                    "product": "AgentDesk support automation platform. [ev-001]",
                    "market": "SMB customer support market. [ev-002]",
                    "why_now": "Rapid AI adoption. [ev-001]",
                    "risks": ["Retention is not yet proven. [ev-002]"],
                    "open_questions": ["What is SMB churn?"],
                    "changes_mind": ["Verified retention metrics", "Customer reference calls"],
                    "score": 90.0,
                    "confidence": 0.85,
                    "recommendation": "Take a meeting",
                    "citations": ["ev-001", "ev-002"],
                }
            return {"output": {"message": {"content": [{"text": json.dumps(payload)}]}}}

    pipeline = Pipeline(bedrock_client=MockBedrockClient())
    result = pipeline.run(
        topic="AI agents for SMBs",
        batch=None,
        limit=None,
        output=tmp_path / "run_dd",
        source_file=source,
        provider=AIProvider.BEDROCK,
        deep_diligence=True,
        max_hops=2,
        now=NOW,
    )

    assert result.succeeded == 1
    assert result.failed == 0
    assert (tmp_path / "run_dd" / "agentdesk.pdf").exists()
    assert (tmp_path / "run_dd" / "agentdesk.pdf").stat().st_size > 0

