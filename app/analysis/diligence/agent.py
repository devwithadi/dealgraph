from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from typing import Any

from app.analysis.diligence.constants import DILIGENCE
from app.analysis.diligence.models import (
    DiligenceEvaluation,
    DiligencePillar,
    DiligencePlan,
    DiligenceState,
    GapSeverity,
    InformationGap,
    SearchQuery,
)
from app.analysis.diligence.tools.ranker import EvidenceRanker
from app.analysis.diligence.tools.scraper import WebFetchTool
from app.analysis.diligence.tools.search import SearchTool, is_allowed_url
from app.core.urls import resolve_host
from app.domain.enums import CitationTag
from app.domain.models import Candidate, Evidence
from app.sourcing.policy import SourcePolicyError

LOGGER = logging.getLogger("dealgraph.diligence")

_is_allowed_url = is_allowed_url
EvaluationFn = Callable[[Candidate, list[Evidence], str, int], DiligenceEvaluation]


def default_live_search(
    candidate: Candidate,
    query_item: SearchQuery,
    start_id: int,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    resolver: Callable[[str], list[str]] = resolve_host,
) -> list[Evidence]:
    """Execute live web search via SearchTool and normalize returned evidence."""
    tool = SearchTool(runner=runner, resolver=resolver)
    return tool.search(candidate, query_item, start_id)


class DeepDiligenceAgent:
    def __init__(
        self,
        *,
        evaluation_fn: EvaluationFn,
        max_hops: int = DILIGENCE.default_max_hops,
        search_fn: Callable[[Candidate, SearchQuery, int], list[Evidence]] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        search_tool: SearchTool | None = None,
        scraper_tool: WebFetchTool | None = None,
        ranker: EvidenceRanker | None = None,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        if max_hops < DILIGENCE.initial_hop:
            raise ValueError("max_hops must be positive")
        self.max_hops = max_hops
        self.evaluation_fn = evaluation_fn
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
        current_evaluation = self.evaluation_fn(
            candidate, base_evidence, topic, DILIGENCE.initial_hop
        )
        plan = DiligencePlan(
            candidate_slug=candidate.slug,
            candidate_name=candidate.name,
            topic=topic,
            queries=current_evaluation.followup_queries,
            focus_areas=[gap.description for gap in current_evaluation.gaps if not gap.resolved],
        )

        self._emit(
            "diligence_plan_generated",
            {
                "candidate": candidate.name,
                "slug": candidate.slug,
                "focus_areas": plan.focus_areas,
                "queries_count": len(plan.queries),
            },
        )

        initial_gaps = current_evaluation.gaps
        state = DiligenceState(
            candidate=candidate,
            topic=topic,
            current_hop=DILIGENCE.unstarted_hop,
            max_hops=self.max_hops,
            plan=plan,
            evidence=base_evidence,
            gaps=initial_gaps,
            queries_executed=[],
            is_complete=False,
            notes=[f"Diligence initialized with {len(base_evidence)} baseline evidence items."],
        )

        # Multi-hop iterative search loop
        current_evidence = list(base_evidence)
        executed_queries: list[SearchQuery] = []
        seen_urls = {ev.source_url for ev in current_evidence}
        current_gaps = list(initial_gaps)
        availability_gap: InformationGap | None = None
        hop = DILIGENCE.unstarted_hop

        # Phase 1: Direct multi-page candidate website scraping
        if candidate.website and candidate.website.strip():
            subpages_list = list(DILIGENCE.website_subpages)
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
            current_evaluation = self.evaluation_fn(
                candidate, current_evidence, topic, DILIGENCE.initial_hop
            )
            current_gaps = current_evaluation.gaps
            self._emit(
                "diligence_scrape_complete",
                {
                    "candidate": candidate.name,
                    "slug": candidate.slug,
                    "scraped_count": len(new_scraped),
                    "total_evidence_count": len(current_evidence),
                },
            )

        for hop_idx in range(DILIGENCE.initial_hop, self.max_hops + 1):
            hop = hop_idx
            pending_queries = list(current_evaluation.followup_queries)

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
                try:
                    if self.search_fn is not None:
                        results = self.search_fn(candidate, q, start_id)
                    else:
                        results = self.search_tool.search(
                            candidate,
                            q,
                            start_id,
                            num_results=DILIGENCE.search_results_per_query,
                        )
                except SourcePolicyError as error:
                    if str(error) != DILIGENCE.search_rate_limited_error:
                        raise
                    availability_gap = InformationGap(
                        pillar=DiligencePillar.RESEARCH_AVAILABILITY,
                        description=DILIGENCE.search_unavailable_gap_description,
                        severity=GapSeverity.HIGH,
                        resolved=False,
                        rationale=DILIGENCE.search_unavailable_gap_rationale,
                    )
                    executed_queries.append(q.model_copy(update={"executed": True}))
                    self._emit(
                        "diligence_search_unavailable",
                        {
                            "candidate": candidate.name,
                            "slug": candidate.slug,
                            "status": DILIGENCE.search_rate_limited_status,
                        },
                    )
                    break

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
            current_evaluation = self.evaluation_fn(
                candidate,
                current_evidence,
                topic,
                hop + DILIGENCE.initial_hop,
            )
            current_gaps = current_evaluation.gaps
            resolved_count = sum(1 for g in current_gaps if g.resolved)
            unresolved_count = sum(1 for g in current_gaps if not g.resolved)

            if availability_gap is not None:
                break

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

            if unresolved_count == DILIGENCE.empty_results_count:
                self._emit(
                    "diligence_all_gaps_resolved",
                    {"candidate": candidate.name, "hop": hop},
                )
                break

        # Final ranking, deduplication, and citation tag assignment
        final_evidence = self.ranker.rank_and_reorder(current_evidence, topic)
        final_gaps = current_evaluation.gaps
        if availability_gap is not None:
            final_gaps = [*final_gaps, availability_gap]

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
