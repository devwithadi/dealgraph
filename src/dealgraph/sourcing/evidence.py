"""Evidence adapters for configured public sources."""

from urllib.parse import urljoin, urlsplit

import httpx

from dealgraph.core.logging import request_headers
from dealgraph.domain.models import Candidate, Evidence
from dealgraph.sourcing.policy import SafeFetcher, SourcePolicyError
from dealgraph.sourcing.registry import HN_URL


def _normalized_host(value: str) -> str:
    return (urlsplit(value).hostname or "").lower().removeprefix("www.")


def yc_evidence(candidate: Candidate) -> list[Evidence]:
    facts = [candidate.one_liner, candidate.description]
    if candidate.team_size is not None:
        facts.append(f"Reported team size: {candidate.team_size}.")
    if candidate.is_hiring:
        facts.append("YC marks the company as hiring.")
    return [
        Evidence(
            id="ev-001",
            claim="YC company profile",
            excerpt=" ".join(filter(None, facts))[:1200],
            source_url=candidate.source_url,
            source_title=f"YC profile: {candidate.name}",
            source_type="yc_directory",
            trust_tier="curated_directory",
            verification="third_party",
            published_at=candidate.launched_at,
        )
    ]


def website_evidence(candidate: Candidate, fetcher: SafeFetcher, start: int) -> list[Evidence]:
    if not candidate.website:
        return []
    root, page = fetcher.html(candidate.website)
    pages = [(root, page)]
    host = urlsplit(root).hostname
    preferred = ("about", "team", "pricing", "customer", "case-stud", "blog")
    links: list[str] = []
    for href in page.links:
        target = urljoin(root, href)
        if urlsplit(target).hostname == host and any(key in target.lower() for key in preferred):
            links.append(target)
    for target in list(dict.fromkeys(links))[:3]:
        try:
            pages.append(fetcher.html(target))
        except (httpx.HTTPError, SourcePolicyError):
            continue
    evidence: list[Evidence] = []
    for offset, (url, parsed) in enumerate(pages):
        excerpt = " ".join(parsed.text)[:1200]
        if excerpt:
            evidence.append(
                Evidence(
                    id=f"ev-{start + offset:03d}",
                    claim=f"Official website content from {parsed.title or urlsplit(url).path or 'homepage'}",
                    excerpt=excerpt,
                    source_url=url,
                    source_title=parsed.title or candidate.name,
                    source_type="company_website",
                    trust_tier="first_party_self_reported",
                    verification="self_reported",
                )
            )
    return evidence


def hn_evidence(candidate: Candidate, client: httpx.Client, evidence_id: int) -> list[Evidence]:
    domain = _normalized_host(candidate.website)
    company_name = candidate.name.lower()

    def matches_candidate(hit: dict) -> bool:
        target = _normalized_host(str(hit.get("url") or hit.get("story_url") or ""))
        if domain and target:
            return target == domain or target.endswith(f".{domain}")
        return company_name in str(hit.get("title") or "").lower()

    response = client.get(
        HN_URL,
        params={"query": domain or candidate.name, "tags": "story", "hitsPerPage": 5},
        headers=request_headers(),
        timeout=10,
    )
    response.raise_for_status()
    hits = response.json().get("hits", [])
    matching_hits = [item for item in hits if matches_candidate(item)]
    if not matching_hits:
        return []
    hit = max(
        matching_hits,
        key=lambda item: (item.get("points") or 0) + (item.get("num_comments") or 0),
    )
    points, comments = hit.get("points") or 0, hit.get("num_comments") or 0
    return [
        Evidence(
            id=f"ev-{evidence_id:03d}",
            claim=f"Hacker News discussion: {points} points and {comments} comments",
            excerpt=str(hit.get("title") or "Hacker News discussion"),
            source_url=f"https://news.ycombinator.com/item?id={hit['objectID']}",
            source_title=str(hit.get("title") or "Hacker News"),
            source_type="hacker_news",
            trust_tier="public_community",
            verification="platform_metric",
            published_at=hit.get("created_at"),
        )
    ]
