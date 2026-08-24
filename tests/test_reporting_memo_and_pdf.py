from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pytest

from app.domain.enums import AIProvider, AnalysisMode, CitationTag, EvidenceStatus, Recommendation
from app.domain.models import Analysis, Candidate, Evidence, Financials
from app.reporting.memo import _build_evidence_map, _format_source_category, render_memo, transform_citations
from app.reporting.pdf import NumberedCanvas, _transform_citations_for_pdf, render_pdf_memo


@pytest.fixture
def sample_candidate() -> Candidate:
    return Candidate(
        slug="vortex-ai",
        name="Vortex AI",
        website="https://vortex.example.ai",
        one_liner="Autonomous data pipelines for real-time fraud detection",
        description="Vortex AI builds streaming data intelligence architecture with sub-millisecond anomaly detection.",
        batch="Summer 2026",
        industry="Cybersecurity / FinTech",
        tags=["AI", "FinTech", "Data Infra"],
        team_size=8,
        launched_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        is_hiring=True,
        source_url="https://api.ycombinator.com/v0.1/companies/vortex-ai",
    )


@pytest.fixture
def sample_evidence() -> list[Evidence]:
    return [
        Evidence(
            id="ev-001",
            claim="YC Company Profile",
            excerpt="Vortex AI builds streaming data intelligence architecture. Reported team size: 8. YC marks company as hiring.",
            source_url="https://api.ycombinator.com/v0.1/companies/vortex-ai",
            source_title="YC Directory: Vortex AI",
            source_type="yc_directory",
            trust_tier="curated_directory",
            verification="third_party",
            status=CitationTag.VERIFIED,
            published_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        ),
        Evidence(
            id="ev-002",
            claim="Product Benchmarks",
            excerpt="Independent benchmarks show Vortex processing 2.5M events/sec at 0.4ms p99 latency.",
            source_url="https://techbenchmarks.io/vortex-2026",
            source_title="TechBenchmarks 2026 Evaluation",
            source_type="deep_diligence_search",
            trust_tier="multi_hop_web",
            verification="multi_hop_search",
            status=CitationTag.TRUSTED,
        ),
        Evidence(
            id="ev-003",
            claim="Commercial Pricing",
            excerpt="Self-reported starter pricing is $2,500/mo enterprise tier with custom volume add-ons.",
            source_url="https://vortex.example.ai/pricing",
            source_title="Vortex Pricing Page",
            source_type="web_scraper",
            trust_tier="self_reported",
            verification="direct_scrape",
            status=CitationTag.CLAIMED,
        ),
    ]


@pytest.fixture
def sample_analysis() -> Analysis:
    return Analysis(
        company="Vortex AI",
        thesis="Vortex AI combines high-throughput event processing with proprietary streaming graph models [ev-002], capturing the enterprise fraud prevention shift from batch to sub-second streaming [ev-001].",
        summary="Vortex provides real-time fraud detection for FinTech and Tier-1 banks [ev-001]. The team demonstrated 2.5M events/sec [ev-002].",
        team="Founders have 10+ years at Databricks and Stripe building streaming infrastructure [ev-001].",
        product="Proprietary streaming graph algorithm running in-memory with sub-millisecond p99 latency [ev-002].",
        market="The real-time fraud detection and compliance market is projected to reach $38B by 2030 [ev-001].",
        why_now="Instant payment rails (FedNow, PIX, SEPA Instant) make batch fraud detection obsolete [ev-001].",
        financials=Financials(
            revenue="$1.2M ARR annualized run rate [ev-003]",
            burn="$65k / month",
            runway="18 months",
            funding="$3.2M Seed led by Tier-1 Angels",
            pricing="$2,500/mo base subscription [ev-003]",
            evidence_ids=["ev-001", "ev-002", "ev-003"],
        ),
        risks=[
            "Competition from legacy vendors like FICO and Snowflake streaming engines [ev-002].",
            "Enterprise sales cycles can stretch from 3 to 9 months in banking.",
        ],
        open_questions=[
            "What is the net revenue retention (NRR) across initial pilot cohort?",
            "How dependent is the graph engine on proprietary GPU kernels?",
        ],
        changes_mind=[
            "Failure to convert 2 Tier-1 bank enterprise pilots to multi-year contracts.",
            "Key engineering team departures from core infrastructure lead.",
        ],
        score=91.5,
        confidence=0.88,
        recommendation=Recommendation.TAKE_A_MEETING,
        analysis_mode=AnalysisMode.BEDROCK,
    )


def test_citation_tag_enums_and_aliases() -> None:
    assert CitationTag.VERIFIED.value == "verified"
    assert CitationTag.TRUSTED.value == "trusted"
    assert CitationTag.CLAIMED.value == "claimed"
    assert EvidenceStatus is CitationTag
    assert str(CitationTag.VERIFIED) == "verified"


def test_evidence_model_has_default_claimed_status() -> None:
    ev = Evidence(
        id="ev-999",
        claim="Claim test",
        excerpt="Excerpt test",
        source_url="https://example.com",
        source_title="Example",
        source_type="generic",
        trust_tier="unverified",
        verification="none",
    )
    assert ev.status == CitationTag.CLAIMED


def test_citation_transformation() -> None:
    ev_map = {
        "ev-001": Evidence(
            id="ev-001",
            claim="YC Profile",
            excerpt="YC snippet",
            source_url="https://ycombinator.com/companies/vortex",
            source_title="YC Directory",
            source_type="yc_directory",
            trust_tier="curated_directory",
            verification="third_party",
            status=CitationTag.VERIFIED,
        ),
        "ev-002": Evidence(
            id="ev-002",
            claim="Benchmark",
            excerpt="Benchmark snippet",
            source_url="https://benchmarks.io/test",
            source_title="Benchmark Report",
            source_type="deep_diligence",
            trust_tier="open_web",
            verification="multi_hop_search",
            status=CitationTag.TRUSTED,
        ),
    }

    raw_text = "Founded in 2026 [ev-001]. Benchmark score is 99% [ev-002]. Multiple [ev-001][ev-002]. Composite [ev-001, ev-002]. Missing citation [ev-999]."
    transformed = transform_citations(raw_text, ev_map)

    assert "[[1] ↗](https://ycombinator.com/companies/vortex)" in transformed
    assert "[[2] ↗](https://benchmarks.io/test)" in transformed
    assert "[[1] ↗](https://ycombinator.com/companies/vortex)[[2] ↗](https://benchmarks.io/test)" in transformed
    assert "[[1] ↗](https://ycombinator.com/companies/vortex) [[2] ↗](https://benchmarks.io/test)" in transformed
    assert "[[EV-999] ↗](#auditable-sources)" in transformed
    assert transform_citations("", ev_map) == ""

    # Test PDF citation transformation
    pdf_transformed = _transform_citations_for_pdf(raw_text, ev_map)
    assert '<a href="https://ycombinator.com/companies/vortex" color="#2563EB"><b>[1] &#8599;</b></a>' in pdf_transformed
    assert '<a href="https://benchmarks.io/test" color="#2563EB"><b>[2] &#8599;</b></a>' in pdf_transformed
    assert '<font color="#64748B"><b>[EV-999]</b></font>' in pdf_transformed
    assert _transform_citations_for_pdf("", ev_map) == ""


def test_render_memo_output_structure(
    sample_candidate: Candidate,
    sample_analysis: Analysis,
    sample_evidence: list[Evidence],
) -> None:
    memo = render_memo(sample_candidate, sample_analysis, sample_evidence)

    # Executive Header & Badges (investor-relevant, no provider jargon)
    assert "# [INVESTMENT COMMITTEE MEMO] Vortex AI" in memo
    assert "🟢 **TAKE A MEETING**" in memo
    assert "`Score: 91.5/100`" in memo
    assert "`Confidence: 88%`" in memo
    assert "`Batch: Summer 2026`" in memo
    assert "Mode: bedrock" not in memo
    assert "bedrock" not in memo.split("---")[0]

    # Quick Metadata table
    assert "| **Website** | [https://vortex.example.ai](https://vortex.example.ai) |" in memo
    assert "| **Batch / Program** | Summer 2026 |" in memo
    assert "| **Sector / Industry** | Cybersecurity / FinTech |" in memo
    assert "| **Team Size** | 8 |" in memo
    assert "| **Hiring Status** | 🟢 Actively Hiring |" in memo

    # 4-Pillar Scorecard Table
    assert "### 4-Pillar Diligence Scorecard" in memo
    assert "| **Commercial / TAM** |" in memo
    assert "| **Financials / Unit Economics** |" in memo
    assert "| **Tech / IP Defensibility** |" in memo
    assert "| **Risk / ESG** |" in memo

    # Callout Quote Blocks
    assert "> 💎 **CROWN JEWEL ASSET:**" in memo
    assert "> ⚠️ **THE INVERSE CASE (Failure Mode & Tripwires):**" in memo

    # Structured Narrative Sections
    assert "## 1. Executive Summary & Investment Thesis" in memo
    assert "## 2. Team & Founder Capability" in memo
    assert "## 3. Product Architecture & TRL" in memo
    assert "## 4. Market Dynamics & Why Now" in memo
    assert "## 5. Financials & Unit Economics" in memo
    assert "## 6. Critical Risks & Stress-Testing" in memo
    assert '## 7. Triggers ("What Would Change Our Mind")' in memo

    # Interactive Compact Citation Links
    assert "[[1] ↗](https://api.ycombinator.com/v0.1/companies/vortex-ai)" in memo
    assert "[[2] ↗](https://techbenchmarks.io/vortex-2026)" in memo
    assert "[[3] ↗](https://vortex.example.ai/pricing)" in memo

    # Auditable Sources Table (clean, investor-facing, no raw ev IDs or internal enum strings)
    assert "## 8. Auditable Sources & References" in memo
    assert "| # | Trust Tag | Source & Publisher | Category | Key Excerpt |" in memo
    assert "| <a id=\"source-1\"></a>[1] | `VERIFIED` | [YC Directory: Vortex AI ↗](https://api.ycombinator.com/v0.1/companies/vortex-ai) | Official Registry |" in memo
    assert "| <a id=\"source-2\"></a>[2] | `TRUSTED` | [TechBenchmarks 2026 Evaluation ↗](https://techbenchmarks.io/vortex-2026) | Web Research |" in memo
    assert "| <a id=\"source-3\"></a>[3] | `CLAIMED` | [Vortex Pricing Page ↗](https://vortex.example.ai/pricing) | Company Website |" in memo
    assert "`ev-001`" not in memo
    assert "deep_diligence_search" not in memo


def test_render_memo_watch_and_pass_decisions(
    sample_candidate: Candidate,
    sample_analysis: Analysis,
    sample_evidence: list[Evidence],
) -> None:
    # Test WATCH
    watch_analysis = Analysis(
        **{**sample_analysis.model_dump(), "recommendation": Recommendation.WATCH, "score": 72.0}
    )
    watch_memo = render_memo(sample_candidate, watch_analysis, sample_evidence)
    assert "🟡 **WATCH**" in watch_memo
    assert "`Score: 72.0/100`" in watch_memo

    # Test PASS with no batch -> Stage: Pre-Seed / Seed
    no_batch_candidate = Candidate(
        **{**sample_candidate.model_dump(), "batch": ""}
    )
    pass_analysis = Analysis(
        **{**sample_analysis.model_dump(), "recommendation": Recommendation.PASS, "score": 45.0}
    )
    pass_memo = render_memo(no_batch_candidate, pass_analysis, sample_evidence)
    assert "🔴 **PASS**" in pass_memo
    assert "`Score: 45.0/100`" in pass_memo
    assert "`Stage: Pre-Seed / Seed`" in pass_memo


def test_source_category_mapping(sample_evidence: list[Evidence]) -> None:
    assert _format_source_category(sample_evidence[0]) == "Official Registry"
    assert _format_source_category(sample_evidence[1]) == "Web Research"
    assert _format_source_category(sample_evidence[2]) == "Company Website"

    press_ev = Evidence(
        id="ev-004",
        claim="News Coverage",
        excerpt="Vortex featured on TechCrunch",
        source_url="https://techcrunch.com/2026/08/vortex-launch",
        source_title="TechCrunch Launch Article",
        source_type="news",
        trust_tier="open_web",
        verification="third_party",
    )
    assert _format_source_category(press_ev) == "Press / Media"


def test_render_pdf_memo_creates_valid_pdf(
    sample_candidate: Candidate,
    sample_analysis: Analysis,
    sample_evidence: list[Evidence],
    tmp_path: Path,
) -> None:
    pdf_out = tmp_path / "vortex_memo.pdf"
    result_path = render_pdf_memo(sample_candidate, sample_analysis, sample_evidence, pdf_out)

    assert result_path == pdf_out.resolve()
    assert pdf_out.exists()
    assert pdf_out.stat().st_size > 1000  # Non-trivial PDF size

    # Verify PDF header magic bytes (%PDF-)
    content = pdf_out.read_bytes()
    assert content.startswith(b"%PDF-")


def test_render_pdf_memo_with_various_recommendations(
    sample_candidate: Candidate,
    sample_analysis: Analysis,
    sample_evidence: list[Evidence],
    tmp_path: Path,
) -> None:
    for rec in (Recommendation.TAKE_A_MEETING, Recommendation.WATCH, Recommendation.PASS):
        test_analysis = Analysis(
            **{**sample_analysis.model_dump(), "recommendation": rec}
        )
        pdf_out = tmp_path / f"memo_{rec.value}.pdf"
        render_pdf_memo(sample_candidate, test_analysis, sample_evidence, pdf_out)
        assert pdf_out.exists()
        assert pdf_out.stat().st_size > 1000


def test_render_pdf_memo_with_multi_paragraph_and_bullets(
    sample_candidate: Candidate,
    sample_evidence: list[Evidence],
    tmp_path: Path,
) -> None:
    multi_para_analysis = Analysis(
        company="Vortex AI",
        thesis="First paragraph of the thesis [ev-001].\n\nSecond paragraph of thesis with deeper reasoning [ev-002].",
        summary="Paragraph 1 of executive summary [ev-001].\n\nParagraph 2 with quantitative traction [ev-002].\n\n• Bullet item one [ev-001]\n• Bullet item two [ev-002]",
        team="### Leadership Background\n\nCEO was previously Staff Engineer at Stripe [ev-001].\n\nCTO holds PhD from Stanford in Distributed Systems [ev-002].",
        product="Core streaming engine processes 2.5M events/sec [ev-002].\n\nArchitecture details:\n• In-memory vector index\n• Real-time graph partitioner",
        market="Bottoms-up TAM sizing reaches $38B [ev-001].\n\nCompetitor comparison indicates strong advantage against legacy batch systems.",
        why_now="FedNow and instant payment mandates [ev-001].\n\nMacro regulatory pressure accelerates compliance timeline.",
        financials=Financials(
            revenue="$1.2M ARR [ev-003]",
            burn="$65k / month",
            runway="18 months",
            funding="$3.2M Seed",
            pricing="Starter: $2,500/mo | Pro: $5,000/mo | Enterprise: Custom [ev-003]",
            evidence_ids=["ev-001", "ev-002", "ev-003"],
        ),
        risks=[
            "Failure scenario 1: High cloud compute cost [ev-002].",
            "Failure scenario 2: Extended banking sales cycles.",
        ],
        open_questions=[
            "What is the net expansion rate across tier-1 pilots?",
        ],
        changes_mind=[
            "Conversion of 2 enterprise pilots.",
            "Key engineering retention milestone.",
        ],
        score=85.0,
        confidence=0.8,
        recommendation=Recommendation.TAKE_A_MEETING,
        analysis_mode=AnalysisMode.BEDROCK,
    )
    pdf_out = tmp_path / "multipara_memo.pdf"
    render_pdf_memo(sample_candidate, multi_para_analysis, sample_evidence, pdf_out)
    assert pdf_out.exists()
    assert pdf_out.stat().st_size > 1000


def test_render_pdf_memo_with_empty_and_minimal_fields(
    sample_candidate: Candidate,
    sample_evidence: list[Evidence],
    tmp_path: Path,
) -> None:
    empty_analysis = Analysis(
        company="Vortex AI",
        thesis="",
        summary="",
        team="",
        product="",
        market="",
        why_now="",
        financials=Financials(),
        risks=["No critical risks evaluated."],
        open_questions=[],
        changes_mind=["Action item 1", "Action item 2"],
        score=40.0,
        confidence=0.2,
        recommendation=Recommendation.PASS,
        analysis_mode=AnalysisMode.BEDROCK,
    )
    pdf_out = tmp_path / "empty_memo.pdf"
    render_pdf_memo(sample_candidate, empty_analysis, sample_evidence, pdf_out)
    assert pdf_out.exists()
    assert pdf_out.stat().st_size > 1000

