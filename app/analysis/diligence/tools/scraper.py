from __future__ import annotations

import html
import logging
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.logging import request_headers
from app.domain.enums import CitationTag
from app.domain.models import Evidence
from app.sourcing.policy import SourcePolicyError, validate_public_url

LOGGER = logging.getLogger("dealgraph.diligence.scraper")

CANONICAL_REGISTRY_DOMAINS = {
    "sec.gov",
    "uspto.gov",
    "companieshouse.gov.uk",
    "ycombinator.com",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._pieces: list[str] = []
        self._in_script_or_style = False
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in {"script", "style", "noscript"}:
            self._in_script_or_style = True
        elif tag_lower == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in {"script", "style", "noscript"}:
            self._in_script_or_style = False
        elif tag_lower == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._in_script_or_style:
            cleaned = data.strip()
            if cleaned:
                self._pieces.append(cleaned)

    def get_text(self) -> str:
        return " ".join(self._pieces)


def extract_html_text(html_content: str) -> tuple[str, str]:
    """Extract clean title and visible body text from HTML string."""
    parser = _TextExtractor()
    try:
        parser.feed(html_content)
        title = html.unescape(parser.title).strip()
        body = html.unescape(parser.get_text()).strip()
        body = re.sub(r"\s+", " ", body)
        return title, body
    except Exception:
        # Fallback regex extraction
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else ""
        cleaned = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_content, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", html.unescape(cleaned)).strip()
        return title, cleaned


class WebFetchTool:
    """Tool for safe website and document fetching with policy validation."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout: float = 10.0,
        max_bytes: int = 150_000,
        url_validator: Any | None = None,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(timeout, connect=5.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=5),
        )
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.url_validator = url_validator or validate_public_url

    def fetch_url(self, url: str) -> tuple[str, str]:
        """Validate URL and fetch content, returning (title, text_content)."""
        safe_url = self.url_validator(url)
        headers = request_headers()
        headers["User-Agent"] = "DealGraph-Diligence/1.0 (+https://dealgraph.internal)"
        response = self.client.get(safe_url, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        content = response.text[: self.max_bytes]
        title, text = extract_html_text(content)
        return title or urlsplit(url).netloc, text

    def scrape_to_evidence(
        self,
        url: str,
        evidence_id: str,
        *,
        claim_prefix: str = "Company website",
        status_override: CitationTag | None = None,
    ) -> Evidence:
        """Fetch a page and convert it into a tagged Evidence object."""
        try:
            title, text = self.fetch_url(url)
        except Exception as error:
            LOGGER.warning("Scraping failed url=%r error=%s", url, error)
            raise SourcePolicyError(f"Unable to scrape URL {url}: {error}") from error

        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if status_override is not None:
            status = status_override
        elif any(host == d or host.endswith(f".{d}") for d in CANONICAL_REGISTRY_DOMAINS):
            status = CitationTag.VERIFIED
        else:
            status = CitationTag.CLAIMED

        return Evidence(
            id=evidence_id,
            claim=f"{claim_prefix}: {title}",
            excerpt=text[:1200],
            source_url=url,
            source_title=title or host,
            source_type="web_scraper",
            trust_tier="self_reported" if status == CitationTag.CLAIMED else "canonical_registry",
            verification="direct_scrape",
            status=status,
        )


ScraperTool = WebFetchTool
