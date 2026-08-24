from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from typing import Any

from app.analysis.diligence.evaluator import evaluate_evidence_gaps, generate_followup_queries
from app.analysis.diligence.models import DiligencePlan, DiligenceState, SearchQuery
from app.analysis.diligence.planner import generate_diligence_plan
from app.analysis.diligence.tools.ranker import EvidenceRanker
from app.analysis.diligence.tools.scraper import WebFetchTool
from app.analysis.diligence.tools.search import SearchTool, is_allowed_url
from app.domain.enums import CitationTag
from app.domain.models import Candidate, Evidence

LOGGER = logging.getLogger("dealgraph.diligence")

_is_allowed_url = is_allowed_url


def default_live_search(
    candidate: Candidate,
    query_item: SearchQuery,
    start_id: int,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[Evidence]:
    """Execute live web search via SearchTool and normalize returned evidence."""
    tool = SearchTool(runner=runner)
    return tool.search(candidate, query_item, start_id)


class DeepDiligenceAgent:
    def __init__(
        self,
        *,
        max_hops: int = 2,
        offline: bool = False,
        search_fn: Callable[[Candidate, SearchQuery, int], list[Evidence]] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        search_tool: SearchTool | None = None,
        scraper_tool: WebFetchTool | None = None,
        ranker: EvidenceRanker | None = None,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.max_hops = max(1, max_hops)
        self.offline = offline
        self.runner = runner
        self.search_fn = search_fn
        self.search_tool = search_tool or SearchTool(runner=runner, custom_search_fn=search_fn)
        self.scraper_tool = scraper_tool or WebFetchTool()
        self.ranker = ranker or EvidenceRanker()
        self.progress_callback = progress_callback

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        if self.progress_callback is not None:
            try:
                self.progress_callback(event, data)
            except Exception:
                pass

    def run(
        self,
        candidate: Candidate,
        topic: str,
        initial_evidence: list[Evidence] | None = None,
    ) -> DiligenceState:
        """Execute the iterative 4-pillar multi-hop deep diligence research workflow."""
        base_evidence = list(initial_evidence or [])
        plan = generate_diligence_plan(candidate, topic, base_evidence)

        self._emit(
            "diligence_plan_generated",
            {
                "candidate": candidate.name,
                "slug": candidate.slug,
                "focus_areas": plan.focus_areas,
                "queries_count": len(plan.queries),
                "offline": self.offline,
            },
        )

        initial_gaps = evaluate_evidence_gaps(candidate, base_evidence, topic)
        state = DiligenceState(
            candidate=candidate,
            topic=topic,
            current_hop=0,
            max_hops=self.max_hops,
            plan=plan,
            evidence=base_evidence,
            gaps=initial_gaps,
            queries_executed=[],
            is_complete=False,
            notes=[f"Diligence initialized with {len(base_evidence)} baseline evidence items."],
        )

        if self.offline:
            # Offline mode: rank and deduplicate local evidence without network calls
            ranked_evidence = self.ranker.rank_and_reorder(base_evidence, topic)
            final_gaps = evaluate_evidence_gaps(candidate, ranked_evidence, topic)
            self._emit(
                "diligence_offline_complete",
                {
                    "candidate": candidate.name,
                    "slug": candidate.slug,
                    "evidence_count": len(ranked_evidence),
                    "gaps_count": len([g for g in final_gaps if not g.resolved]),
                },
            )
            return DiligenceState(
                candidate=state.candidate,
                topic=state.topic,
                current_hop=0,
                max_hops=self.max_hops,
                plan=state.plan,
                evidence=ranked_evidence,
                gaps=final_gaps,
                queries_executed=[],
                is_complete=True,
                notes=state.notes + ["Offline mode diligence completed."],
            )

        # Multi-hop iterative search loop
        current_evidence = list(base_evidence)
        executed_queries: list[SearchQuery] = []
        seen_urls = {ev.source_url for ev in current_evidence}
        current_gaps = list(initial_gaps)
        hop = 0

        # Phase 1: Direct multi-page candidate website scraping
        if candidate.website and candidate.website.strip():
            subpages_list = ["/", "/pricing", "/about", "/product", "/docs", "/security", "/faq", "/blog"]
            self._emit(
                "diligence_scrape_start",
                {
                    "candidate": candidate.name,
                    "slug": candidate.slug,
                    "website": candidate.website.strip(),
                    "subpages": subpages_list,
                },
            )

            def _on_subpage_scraped(subpage: str, title: str, length: int) -> None:
                self._emit(
                    "diligence_scrape_page",
                    {
                        "candidate": candidate.name,
                        "slug": candidate.slug,
                        "subpage": subpage,
                        "title": title,
                        "length": length,
                    },
                )

            scraped_items = self.scraper_tool.scrape_candidate_pages(
                candidate,
                start_id=len(current_evidence) + 1,
                on_page_scraped=_on_subpage_scraped,
            )

            new_scraped: list[Evidence] = []
            for item in scraped_items:
                if item.source_url not in seen_urls:
                    seen_urls.add(item.source_url)
                    new_scraped.append(item)

            current_evidence.extend(new_scraped)
            current_gaps = evaluate_evidence_gaps(candidate, current_evidence, topic)
            self._emit(
                "diligence_scrape_complete",
                {
                    "candidate": candidate.name,
                    "slug": candidate.slug,
                    "scraped_count": len(new_scraped),
                    "total_evidence_count": len(current_evidence),
                },
            )

        for hop_idx in range(1, self.max_hops + 1):
            hop = hop_idx
            if hop == 1:
                pending_queries = list(plan.queries)
            else:
                pending_queries = generate_followup_queries(candidate, current_gaps, hop=hop, topic=topic)

            if not pending_queries:
                self._emit(
                    "diligence_hop_skipped",
                    {"hop": hop, "reason": "No pending information gaps require follow-up queries."},
                )
                break

            self._emit(
                "diligence_hop_start",
                {
                    "candidate": candidate.name,
                    "slug": candidate.slug,
                    "hop": hop,
                    "max_hops": self.max_hops,
                    "queries": [q.query for q in pending_queries],
                    "pillars": [q.pillar for q in pending_queries],
                },
            )

            hop_new_evidence: list[Evidence] = []
            for q in pending_queries:
                self._emit(
                    "diligence_query_start",
                    {
                        "candidate": candidate.name,
                        "slug": candidate.slug,
                        "query": q.query,
                        "pillar": q.pillar,
                        "hop": hop,
                    },
                )
                start_id = len(current_evidence) + len(hop_new_evidence) + 1
                if self.search_fn is not None:
                    results = self.search_fn(candidate, q, start_id)
                else:
                    results = self.search_tool.search(candidate, q, start_id, num_results=5)

                unique_results: list[Evidence] = []
                for res in results:
                    if res.source_url not in seen_urls:
                        seen_urls.add(res.source_url)
                        unique_results.append(res)
                        self._emit(
                            "diligence_evidence_collected",
                            {
                                "candidate": candidate.name,
                                "id": res.id,
                                "title": res.source_title,
                                "url": res.source_url,
                                "pillar": q.pillar,
                                "status": res.status.value if hasattr(res.status, "value") else str(res.status),
                            },
                        )

                hop_new_evidence.extend(unique_results)
                executed_queries.append(
                    SearchQuery(
                        query=q.query,
                        pillar=q.pillar,
                        rationale=q.rationale,
                        hop=hop,
                        executed=True,
                        results_count=len(unique_results),
                    )
                )

            current_evidence.extend(hop_new_evidence)
            current_gaps = evaluate_evidence_gaps(candidate, current_evidence, topic)
            resolved_count = sum(1 for g in current_gaps if g.resolved)
            unresolved_count = sum(1 for g in current_gaps if not g.resolved)

            self._emit(
                "diligence_hop_complete",
                {
                    "candidate": candidate.name,
                    "slug": candidate.slug,
                    "hop": hop,
                    "new_evidence_count": len(hop_new_evidence),
                    "total_evidence_count": len(current_evidence),
                    "resolved_gaps": resolved_count,
                    "unresolved_gaps": unresolved_count,
                },
            )

            if unresolved_count == 0:
                self._emit(
                    "diligence_all_gaps_resolved",
                    {"candidate": candidate.name, "hop": hop},
                )
                break

        # Final ranking, deduplication, and citation tag assignment
        final_evidence = self.ranker.rank_and_reorder(current_evidence, topic)
        final_gaps = evaluate_evidence_gaps(candidate, final_evidence, topic)

        final_notes = [
            f"Executed {len(executed_queries)} research queries across {hop} hops.",
            f"Collected {len(final_evidence)} ranked evidence items.",
        ]

        return DiligenceState(
            candidate=candidate,
            topic=topic,
            current_hop=hop,
            max_hops=self.max_hops,
            plan=plan,
            evidence=final_evidence,
            gaps=final_gaps,
            queries_executed=executed_queries,
            is_complete=True,
            notes=final_notes,
        )
