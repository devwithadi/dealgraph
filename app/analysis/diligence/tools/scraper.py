from __future__ import annotations

import concurrent.futures
import html
import logging
import re
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.logging import request_headers
from app.domain.enums import CitationTag
from app.domain.models import Candidate, Evidence
from app.sourcing.policy import SourcePolicyError, validate_public_url

LOGGER = logging.getLogger("dealgraph.diligence.scraper")

CANONICAL_REGISTRY_DOMAINS = {
    "sec.gov",
    "uspto.gov",
    "companieshouse.gov.uk",
    "ycombinator.com",
}

DEFAULT_SUBPAGES: tuple[str, ...] = ("/", "/pricing", "/about", "/product", "/docs", "/security")


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

    def scrape_candidate_pages(
        self,
        candidate: Candidate,
        start_id: int = 1,
        *,
        subpages: list[str] | tuple[str, ...] | None = None,
        on_page_scraped: Callable[[str, str, int], None] | None = None,
    ) -> list[Evidence]:
        """Scrape key subpages of a candidate website concurrently."""
        website = candidate.website.strip()
        if not website:
            return []

        parsed = urlsplit(website)
        scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "https"
        netloc = parsed.netloc or parsed.path.split("/")[0]
        if not netloc:
            return []
        base_origin = f"{scheme}://{netloc}"

        pages_to_scrape = subpages or DEFAULT_SUBPAGES
        urls: list[tuple[str, str]] = []  # (subpage_key, full_url)
        for page in pages_to_scrape:
            page_clean = page.strip()
            if page_clean in {"", "/"}:
                urls.append(("/", f"{base_origin}/"))
            else:
                clean_path = page_clean.lstrip("/")
                urls.append((f"/{clean_path}", f"{base_origin}/{clean_path}"))

        def _fetch_single(item: tuple[str, str]) -> tuple[str, str, str, str] | None:
            subpage_key, url = item
            try:
                title, text = self.fetch_url(url)
                if len(text.strip()) >= 30:
                    return subpage_key, url, title, text
            except Exception as error:
                LOGGER.debug("Subpage scrape skipped url=%r error=%s", url, error)
            return None

        results: list[tuple[str, str, str, str]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(urls), 6)) as executor:
            future_to_item = {executor.submit(_fetch_single, u): u for u in urls}
            for future in concurrent.futures.as_completed(future_to_item):
                res = future.result()
                if res is not None:
                    results.append(res)

        order = {u[1]: idx for idx, u in enumerate(urls)}
        results.sort(key=lambda r: order.get(r[1], 999))

        evidence_items: list[Evidence] = []
        for idx, (subpage_key, url, title, text) in enumerate(results):
            ev_id = f"ev-{start_id + idx:03d}"
            subpage_label = "Home" if subpage_key == "/" else subpage_key.lstrip("/").capitalize()
            claim = f"Company website [{subpage_label}]: {title}"
            evidence = Evidence(
                id=ev_id,
                claim=claim,
                excerpt=text[:1200],
                source_url=url,
                source_title=title or f"{candidate.name} {subpage_label}",
                source_type="web_scraper",
                trust_tier="self_reported",
                verification="direct_scrape",
                status=CitationTag.CLAIMED,
            )
            evidence_items.append(evidence)
            if on_page_scraped is not None:
                try:
                    on_page_scraped(subpage_key, title, len(text))
                except Exception:
                    pass

        return evidence_items


ScraperTool = WebFetchTool
