from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FinalistReportItem:
    name: str
    slug: str
    decision: str
    score: float | None
    confidence: float | None
    memo_path: str
    pdf_memo_path: str = ""
    error: str | None = None


class ConsoleReporter:
    def __init__(self) -> None:
        self._finalist_items: list[FinalistReportItem] = []

    @property
    def finalist_items(self) -> list[FinalistReportItem]:
        return list(self._finalist_items)

    def __call__(self, event: str, data: dict[str, Any]) -> None:
        if event == "header":
            self._print_header(data)
        elif event == "replay_header":
            self._print_replay_header(data)
        elif event == "sourcing_start":
            print(f"[Sourcing] Sourcing candidates from {data.get('source')}...")
        elif event == "sourcing_complete":
            print(
                f"[Sourcing] Sourced {data.get('count')} candidate(s) within the last "
                f"{data.get('lookback_days')} days."
            )
        elif event == "screening_start":
            print(
                f"\n[Screening] Evaluating {data.get('total')} candidates in batches of "
                f"{data.get('batch_size')}..."
            )
        elif event == "screening_batch":
            batch_num = data.get("batch_number", 1)
            total_batches = data.get("total_batches", 1)
            start = data.get("start_index", 1)
            end = data.get("end_index", 1)
            print(f"\n[Screening] Batch {batch_num}/{total_batches} (candidates {start}-{end}):")
            for decision in data.get("decisions", []):
                name = decision.get("name", decision.get("slug"))
                score = decision.get("fit_score", 0.0)
                advance = decision.get("advance", False)
                rationale = decision.get("rationale", "")
                tag = "[+]" if advance else "[-]"
                action = "ADVANCE" if advance else "PASS"
                score_str = f"{score:.1f}" if isinstance(score, float) else f"{score}"
                print(f"  {tag} {name} (Fit: {score_str}/100 | {action}) - {rationale}")
        elif event == "screening_complete":
            print(
                f"\n[Screening] Screening complete: {data.get('advancing')}/{data.get('total')} "
                f"candidates advancing to diligence."
            )
        elif event == "diligence_start":
            total = data.get("total", 0)
            print(f"\n[Diligence & Synthesis] Processing {total} finalists...")
        elif event == "finalist_start":
            index = data.get("index", 1)
            total = data.get("total", 1)
            name = data.get("name", "")
            slug = data.get("slug", "")
            print(f"\n[{index}/{total}] {name} (slug: {slug})")
        elif event == "finalist_evidence":
            total = data.get("count", 0)
            yc_count = data.get("yc_count", 0)
            reach_count = data.get("reach_count", 0)
            source_label = "Deep Diligence" if data.get("deep_diligence") else "Agent Reach"
            print(f"  - Evidence: Found {total} records ({yc_count} YC, {reach_count} {source_label}).")
        elif event == "diligence_plan_generated":
            queries_count = data.get("queries_count", 0)
            candidate = data.get("candidate", "")
            print(f"  - Diligence Plan: Generated {queries_count} research queries across 4 pillars for {candidate}.")
        elif event == "diligence_scrape_start":
            website = data.get("website", "")
            subpages = data.get("subpages", [])
            subpages_str = f" ({', '.join(subpages)})" if subpages else ""
            print(f"  - Diligence Scraping: Scraping candidate website {website}{subpages_str}...")
        elif event == "diligence_scrape_page":
            subpage = data.get("subpage", "")
            title = data.get("title", "")
            length = data.get("length", 0)
            print(f"    * Scraped [{subpage}]: {title} ({length} chars)")
        elif event == "diligence_scrape_complete":
            scraped_count = data.get("scraped_count", 0)
            total_count = data.get("total_evidence_count", 0)
            print(f"    Direct scraping complete: {scraped_count} subpage(s) captured ({total_count} total evidence).")
        elif event == "diligence_hop_start":
            hop = data.get("hop", 1)
            max_hops = data.get("max_hops", 1)
            queries = data.get("queries", [])
            pillars = data.get("pillars", [])
            pillars_str = f" ({', '.join(set(pillars))})" if pillars else ""
            print(f"  - Diligence [Hop {hop}/{max_hops}]: Executing {len(queries)} research queries{pillars_str}...")
            for query in queries:
                print(f"    * Search: {query}")
        elif event == "diligence_query_start":
            pillar = data.get("pillar", "")
            query = data.get("query", "")
            print(f"    * Search [{pillar}]: {query}")
        elif event == "diligence_evidence_collected":
            id_ = data.get("id", "")
            status = data.get("status", "")
            title = data.get("title", "")
            url = data.get("url", "")
            print(f"      + [{id_}] [{status}] {title} ({url})")
        elif event == "diligence_hop_complete":
            hop = data.get("hop", 1)
            new_ev = data.get("new_evidence_count", 0)
            total_ev = data.get("total_evidence_count", 0)
            resolved = data.get("resolved_gaps", 0)
            unresolved = data.get("unresolved_gaps", 0)
            print(
                f"  - Diligence [Hop {hop} Complete]: +{new_ev} new evidence ({total_ev} total) | "
                f"Gaps: {resolved} resolved, {unresolved} pending"
            )
        elif event == "diligence_all_gaps_resolved":
            candidate = data.get("candidate", "")
            hop = data.get("hop", 1)
            print(f"  - Diligence: All 4-pillar information gaps resolved for {candidate} in hop {hop}.")
        elif event == "diligence_offline_complete":
            candidate = data.get("candidate", "")
            ev_count = data.get("evidence_count", 0)
            gaps = data.get("gaps_count", 0)
            print(f"  - Diligence (Offline): Evaluated {ev_count} local evidence items for {candidate} ({gaps} gaps).")
        elif event == "finalist_synthesis_start":
            model = data.get("model", "")
            print(f"  - Synthesis: Generating investment memo with {model}...")
        elif event == "finalist_success":
            decision = data.get("decision", "")
            score = data.get("score", 0.0)
            confidence = data.get("confidence", 0.0)
            memo_path = data.get("memo_path", "")
            pdf_memo_path = data.get("pdf_memo_path", "")
            score_str = f"{score:.1f}" if isinstance(score, float) else f"{score}"
            conf_str = f"{confidence:.2f}" if isinstance(confidence, float) else f"{confidence}"
            print(f"  - Result: Decision: {decision} | Score: {score_str}/100 | Confidence: {conf_str}")
            print(f"  - Markdown Memo: {memo_path}")
            if pdf_memo_path:
                print(f"  - PDF Memo:      {pdf_memo_path}")
                print(f"    View command:  open {pdf_memo_path}")
            self._finalist_items.append(
                FinalistReportItem(
                    name=str(data.get("name", "")),
                    slug=str(data.get("slug", "")),
                    decision=str(decision),
                    score=score if isinstance(score, (int, float)) else None,
                    confidence=confidence if isinstance(confidence, (int, float)) else None,
                    memo_path=str(memo_path),
                    pdf_memo_path=str(pdf_memo_path),
                )
            )
        elif event == "finalist_failure":
            error = str(data.get("error", "Unknown error"))
            print(f"  - Failed: {error}")
            self._finalist_items.append(
                FinalistReportItem(
                    name=str(data.get("name", "")),
                    slug=str(data.get("slug", "")),
                    decision="Failed",
                    score=None,
                    confidence=None,
                    memo_path="N/A",
                    pdf_memo_path="N/A",
                    error=error,
                )
            )
        elif event == "summary_table":
            self.print_summary_table()

    def _print_header(self, data: dict[str, Any]) -> None:
        divider = "=" * 80
        print(divider)
        print("DealGraph Pipeline Run")
        print(f"Topic: {data.get('topic')}")
        lookback = data.get("lookback_days")
        cutoff = data.get("cutoff")
        print(f"Lookback Window: {lookback} days (Cutoff: {cutoff})")
        provider = data.get("provider")
        provider_name = provider.value if hasattr(provider, "value") else str(provider)
        print(f"Provider: {provider_name}")
        print(f"Screening Model: {data.get('screening_model')}")
        print(f"Synthesis Model: {data.get('synthesis_model')}")
        print(f"Output Directory: {data.get('output')}")
        print(divider)

    def _print_replay_header(self, data: dict[str, Any]) -> None:
        divider = "=" * 80
        print(divider)
        print("DealGraph Replay Mode (Offline Re-generation)")
        print(f"Run Directory: {data.get('run_dir')}")
        print(f"Analyses to Replay: {data.get('total_analyses')}")
        print(divider)

    def print_summary_table(self) -> None:
        divider = "=" * 80
        thin_divider = "-" * 80
        print(f"\n{divider}")
        print("Finalist Summary")
        print(thin_divider)
        if not self._finalist_items:
            print("No finalists advanced to diligence.")
            print(f"{divider}\n")
            return

        header = f"{'Company':<20} {'Decision':<16} {'Score':<8} {'Confidence':<12} {'Memo (MD)':<22} {'Memo (PDF)'}"
        print(header)
        print(thin_divider)
        for item in self._finalist_items:
            score_str = f"{item.score:.1f}" if item.score is not None else "N/A"
            conf_str = f"{item.confidence:.2f}" if item.confidence is not None else "N/A"
            pdf_str = item.pdf_memo_path if item.pdf_memo_path else "N/A"
            print(f"{item.name:<20} {item.decision:<16} {score_str:<8} {conf_str:<12} {item.memo_path:<22} {pdf_str}")
        print(f"{divider}")

        pdf_items = [item for item in self._finalist_items if item.pdf_memo_path and item.pdf_memo_path != "N/A"]
        if pdf_items:
            print("\nGenerated PDF Investment Memos:")
            for item in pdf_items:
                print(f"  PDF Memo:     {item.pdf_memo_path}")
                print(f"  View command: open {item.pdf_memo_path}")
        print()
