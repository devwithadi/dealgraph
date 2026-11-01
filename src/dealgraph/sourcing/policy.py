"""SSRF-safe public HTML fetching with robots enforcement."""

from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from dealgraph.core.errors import AppError
from dealgraph.core.logging import USER_AGENT, request_headers
from dealgraph.core.urls import PublicUrlError, resolve_host, validate_public_url as validate_target

BLOCKED_HOSTS = {"pitchbook.com", "crunchbase.com", "linkedin.com"}
MAX_RESPONSE_BYTES = 2_000_000


class SourcePolicyError(AppError, ValueError):
    pass


def validate_public_url(
    url: str,
    resolver: Callable[[str], list[str]] = resolve_host,
) -> str:
    """Reject credentials, unusual ports, blocked vendors, and non-public targets."""
    try:
        return validate_target(
            url,
            schemes={"http", "https"},
            ports={80, 443},
            blocked_hosts=BLOCKED_HOSTS,
            resolver=resolver,
        )
    except PublicUrlError as error:
        raise SourcePolicyError(str(error)) from error


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
        resolver: Callable[[str], list[str]] = resolve_host,
    ) -> None:
        self.client, self.resolver = client, resolver
        self._robots: dict[str, RobotFileParser] = {}

    def _robots_allowed(self, url: str) -> bool:
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            robots = RobotFileParser(f"{origin}/robots.txt")
            try:
                response = self.client.get(robots.url, headers=request_headers(), timeout=5)
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
                headers=request_headers(),
                timeout=10,
                follow_redirects=False,
            )
            if response.is_redirect:
                current = validate_public_url(
                    urljoin(current, response.headers["location"]), self.resolver
                )
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
