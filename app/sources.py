"""Public-source loading, safe fetching, and minimal HTML extraction."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.models import Candidate, Evidence

YC_URL = "https://yc-oss.github.io/api/companies/all.json"
HN_URL = "https://hn.algolia.com/api/v1/search_by_date"
SOURCE_REGISTRY = {
    "yc": {"url": YC_URL, "access": "public_api", "trust": "curated_directory", "enabled": True},
    "hacker_news": {"url": HN_URL, "access": "public_api", "trust": "public_community", "enabled": True},
    "company_website": {"access": "public_html", "trust": "first_party_self_reported", "enabled": True},
    "pitchbook": {"access": "licensed_api_only", "trust": "licensed_vendor", "enabled": False},
}
BLOCKED_HOSTS = {"pitchbook.com", "crunchbase.com", "linkedin.com"}
USER_AGENT = "IDA-case-study/1.0 (public research; contact in repository)"
MAX_RESPONSE_BYTES = 2_000_000


class SourcePolicyError(ValueError):
    pass


def _default_resolver(host: str) -> list[str]:
    return list({item[4][0] for item in socket.getaddrinfo(host, None)})


def validate_public_url(
    url: str,
    resolver: Callable[[str], list[str]] = _default_resolver,
) -> str:
    """Reject credentials, unusual ports, blocked vendors, and non-public targets."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SourcePolicyError(f"Unsupported URL: {url}")
    if parsed.username or parsed.password:
        raise SourcePolicyError("Credentials in URLs are forbidden")
    try:
        port = parsed.port
    except ValueError as error:
        raise SourcePolicyError("Invalid port") from error
    if port not in {None, 80, 443}:
        raise SourcePolicyError("Only ports 80 and 443 are allowed")
    host = parsed.hostname.rstrip(".").lower()
    if any(host == blocked or host.endswith(f".{blocked}") for blocked in BLOCKED_HOSTS):
        raise SourcePolicyError(f"Source is blocked by policy: {host}")
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        addresses = resolver(host)
    if not addresses:
        raise SourcePolicyError(f"Host did not resolve: {host}")
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise SourcePolicyError(f"Non-public target rejected: {address}")
    return url


def _batch_name(batch: str | None) -> str:
    value = (batch or "").strip().lower()
    match = re.fullmatch(r"([ws])\s*(\d{2})", value)
    if match:
        return f"{'winter' if match.group(1) == 'w' else 'summer'} 20{match.group(2)}"
    return value


def _topic_tokens(topic: str) -> set[str]:
    stop = {"and", "for", "from", "the", "with"}
    return {
        word.rstrip("s")
        for word in re.findall(r"[a-z0-9]+", topic.lower())
        if word not in stop and (len(word) > 2 or word == "ai")
    }


def _normalized_host(value: str) -> str:
    return (urlsplit(value).hostname or "").lower().removeprefix("www.")


def _candidate(record: dict) -> Candidate:
    launched = record.get("launched_at")
    return Candidate(
        slug=str(record.get("slug") or record["id"]),
        name=str(record["name"]),
        website=str(record.get("website") or ""),
        one_liner=str(record.get("one_liner") or ""),
        description=str(record.get("long_description") or ""),
        batch=str(record.get("batch") or ""),
        industry=str(record.get("subindustry") or record.get("industry") or ""),
        tags=[str(tag) for tag in record.get("tags") or []],
        team_size=record.get("team_size"),
        launched_at=datetime.fromtimestamp(int(launched), timezone.utc) if launched else None,
        is_hiring=bool(record.get("isHiring")),
        source_url=str(record.get("url") or YC_URL),
    )


def filter_candidates(
    records: Iterable[dict], topic: str, batch: str | None, limit: int
) -> list[Candidate]:
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    expected_batch, tokens = _batch_name(batch), _topic_tokens(topic)
    ranked: list[tuple[int, Candidate]] = []
    seen: set[str] = set()
    for record in records:
        if str(record.get("status", "Active")).lower() != "active":
            continue
        candidate = _candidate(record)
        if expected_batch and candidate.batch.lower() != expected_batch:
            continue
        domain = (urlsplit(candidate.website).hostname or candidate.slug).lower()
        if domain in seen:
            continue
        haystack = " ".join(
            [candidate.name, candidate.one_liner, candidate.description, *candidate.tags]
        ).lower()
        score = sum(token in haystack for token in tokens)
        if tokens and not score:
            continue
        seen.add(domain)
        ranked.append((score, candidate))
    ranked.sort(
        key=lambda item: (
            item[0],
            item[1].launched_at or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    return [candidate for _, candidate in ranked[:limit]]


def load_candidates(
    source_file: Path, topic: str, batch: str | None, limit: int
) -> list[Candidate]:
    return filter_candidates(json.loads(source_file.read_text()), topic, batch, limit)


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self._in_title = False
        self.title = ""
        self.text: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg", "noscript"}:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "noscript"} and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value or self._skip:
            return
        if self._in_title:
            self.title = f"{self.title} {value}".strip()
        self.text.append(value)


class SafeFetcher:
    def __init__(
        self,
        client: httpx.Client,
        resolver: Callable[[str], list[str]] = _default_resolver,
    ) -> None:
        self.client, self.resolver = client, resolver
        self._robots: dict[str, RobotFileParser] = {}

    def _robots_allowed(self, url: str) -> bool:
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            robots = RobotFileParser(f"{origin}/robots.txt")
            try:
                response = self.client.get(robots.url, headers={"user-agent": USER_AGENT}, timeout=5)
                robots.parse(response.text.splitlines() if response.status_code == 200 else [])
            except httpx.HTTPError:
                robots.parse([])
            self._robots[origin] = robots
        return self._robots[origin].can_fetch(USER_AGENT, url)

    def html(self, url: str) -> tuple[str, PageParser]:
        current = validate_public_url(url, self.resolver)
        for _ in range(4):
            if not self._robots_allowed(current):
                raise SourcePolicyError(f"robots.txt disallows {current}")
            response = self.client.get(
                current,
                headers={"user-agent": USER_AGENT},
                timeout=10,
                follow_redirects=False,
            )
            if response.is_redirect:
                current = validate_public_url(urljoin(current, response.headers["location"]), self.resolver)
                continue
            response.raise_for_status()
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise SourcePolicyError("Response exceeded 2 MB")
            if "text/html" not in response.headers.get("content-type", "text/html"):
                raise SourcePolicyError("Expected an HTML response")
            parser = PageParser()
            parser.feed(response.text)
            return current, parser
        raise SourcePolicyError("Too many redirects")


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
        headers={"user-agent": USER_AGENT},
        timeout=10,
    )
    response.raise_for_status()
    hits = response.json().get("hits", [])
    if not hits:
        return []
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
