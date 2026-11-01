from dataclasses import dataclass

from app.domain.enums import CitationTag


@dataclass(frozen=True)
class DiligenceConstants:
    unstarted_hop: int = 0
    initial_hop: int = 1
    empty_results_count: int = 0
    default_max_hops: int = 2
    evaluation_stage: str = "diligence_evaluation"
    evaluation_max_tokens: int = 2_400
    search_results_per_query: int = 5
    search_rate_limited_error: str = "Independent search rate limited"
    search_rate_limited_status: str = "rate_limited"
    search_unavailable_gap_description: str = (
        "Independent search was rate limited; the memo uses available baseline and first-party sources."
    )
    search_unavailable_gap_rationale: str = (
        "Search provider returned a quota response; no provider body was retained."
    )
    website_subpages: tuple[str, ...] = (
        "/",
        "/pricing",
        "/about",
        "/product",
        "/docs",
        "/security",
        "/faq",
        "/blog",
    )
    relevance_base_score: float = 1.0
    topic_match_score: float = 2.0
    detailed_excerpt_characters: int = 100
    detailed_excerpt_score: float = 0.5
    verified_score: float = 2.0
    trusted_score: float = 1.0
    citation_priority: tuple[CitationTag, ...] = (
        CitationTag.VERIFIED,
        CitationTag.TRUSTED,
        CitationTag.CLAIMED,
    )


DILIGENCE = DiligenceConstants()
