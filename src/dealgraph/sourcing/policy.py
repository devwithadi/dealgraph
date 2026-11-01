"""SSRF-safe public HTML fetching with robots enforcement."""

import ipaddress
import socket
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from dealgraph.core.errors import AppError
from dealgraph.core.logging import USER_AGENT, request_headers

BLOCKED_HOSTS = {"pitchbook.com", "crunchbase.com", "linkedin.com"}
MAX_RESPONSE_BYTES = 2_000_000


class SourcePolicyError(AppError, ValueError):
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
