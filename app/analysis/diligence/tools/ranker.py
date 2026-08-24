from __future__ import annotations

from urllib.parse import urlsplit

from app.analysis.diligence.constants import DILIGENCE
from app.domain.enums import CitationTag
from app.domain.models import Evidence

VERIFIED_DOMAINS = {
    "ycombinator.com",
    "sec.gov",
    "uspto.gov",
    "companieshouse.gov.uk",
    "edgar-online.com",
    "whois.arin.net",
}


def normalize_url(url: str) -> str:
    """Normalize URL by stripping fragments, trailing slashes, and standardizing host."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    scheme = parsed.scheme.lower() or "https"
    return f"{scheme}://{host}{path}{query}"


class EvidenceRanker:
    """Ranks, deduplicates, and validates citation statuses for diligence evidence."""

    def __init__(self, *, verified_domains: set[str] | None = None) -> None:
        self.verified_domains = verified_domains or VERIFIED_DOMAINS

    def assign_citation_tag(self, item: Evidence) -> CitationTag:
        """Assign or validate the appropriate CitationTag for an evidence item."""
        if item.source_type == "yc_directory":
            return CitationTag.VERIFIED

        parsed = urlsplit(item.source_url)
        host = (parsed.hostname or "").lower()

        if any(host == d or host.endswith(f".{d}") for d in self.verified_domains):
            return CitationTag.VERIFIED

        if item.trust_tier == "first_party" or item.source_type in {
            "web_scraper",
            "landing_page",
            "self_reported",
        }:
            return CitationTag.CLAIMED

        if item.trust_tier in {"curated_directory", "government_registry", "audit"}:
            return CitationTag.VERIFIED

        if item.source_type in {"agent_reach", "deep_diligence", "deep_diligence_search", "news"}:
            return CitationTag.TRUSTED

        # Retain existing status if valid, else default to CLAIMED
        if isinstance(item.status, CitationTag):
            return item.status
        return CitationTag.CLAIMED

    def score_relevance(self, item: Evidence, topic: str = "") -> float:
        """Score evidence relevance based on text length, pillar keywords, and topic overlap."""
        text = f"{item.claim} {item.excerpt} {item.source_title}".lower()
        score = DILIGENCE.relevance_base_score

        # Topic match boost
        if topic and any(token in text for token in topic.lower().split()):
            score += DILIGENCE.topic_match_score

        # Quality factors
        if len(item.excerpt.strip()) > DILIGENCE.detailed_excerpt_characters:
            score += DILIGENCE.detailed_excerpt_score
        if item.status == CitationTag.VERIFIED:
            score += DILIGENCE.verified_score
        elif item.status == CitationTag.TRUSTED:
            score += DILIGENCE.trusted_score

        return score

    def deduplicate(self, evidence_list: list[Evidence]) -> list[Evidence]:
        """Deduplicate evidence items by normalized URL and content snippet similarity."""
        seen_urls: set[str] = set()
        seen_snippets: set[str] = set()
        deduped: list[Evidence] = []

        for item in evidence_list:
            norm_url = normalize_url(item.source_url) if item.source_url else ""
            snippet_key = item.excerpt[:80].strip().lower()

            if norm_url and norm_url in seen_urls:
                continue
            if snippet_key and snippet_key in seen_snippets:
                continue

            if norm_url:
                seen_urls.add(norm_url)
            if snippet_key:
                seen_snippets.add(snippet_key)

            # Ensure tag is properly assigned
            corrected_status = self.assign_citation_tag(item)
            if corrected_status != item.status:
                item = Evidence(
                    id=item.id,
                    claim=item.claim,
                    excerpt=item.excerpt,
                    source_url=item.source_url,
                    source_title=item.source_title,
                    source_type=item.source_type,
                    trust_tier=item.trust_tier,
                    verification=item.verification,
                    status=corrected_status,
                    published_at=item.published_at,
                    retrieved_at=item.retrieved_at,
                )
            deduped.append(item)

        return deduped

    def rank_and_reorder(
        self,
        evidence_list: list[Evidence],
        topic: str = "",
    ) -> list[Evidence]:
        """Deduplicate, score, and reorder evidence items with renumbered IDs."""
        deduped = self.deduplicate(evidence_list)

        def sort_key(item: Evidence) -> tuple[int, float]:
            tag_priority = (
                DILIGENCE.citation_priority.index(item.status)
                if item.status in DILIGENCE.citation_priority
                else len(DILIGENCE.citation_priority)
            )
            relevance = self.score_relevance(item, topic)
            return (tag_priority, -relevance)

        scored = sorted(deduped, key=sort_key)
        ranked: list[Evidence] = []
        for priority in range(len(DILIGENCE.citation_priority) + 1):
            remaining = [item for item in scored if sort_key(item)[0] == priority]
            while remaining:
                seen_hosts: set[str] = set()
                deferred: list[Evidence] = []
                for item in remaining:
                    host = (urlsplit(item.source_url).hostname or item.source_url).lower().removeprefix("www.")
                    if host in seen_hosts:
                        deferred.append(item)
                    else:
                        seen_hosts.add(host)
                        ranked.append(item)
                remaining = deferred

        # Renumber sequentially starting from ev-001
        renumbered: list[Evidence] = []
        for idx, item in enumerate(ranked, start=1):
            renumbered.append(
                Evidence(
                    id=f"ev-{idx:03d}",
                    claim=item.claim,
                    excerpt=item.excerpt,
                    source_url=item.source_url,
                    source_title=item.source_title,
                    source_type=item.source_type,
                    trust_tier=item.trust_tier,
                    verification=item.verification,
                    status=item.status,
                    published_at=item.published_at,
                    retrieved_at=item.retrieved_at,
                )
            )
        return renumbered
