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

DEFAULT_SUBPAGES: tuple[str, ...] = (
    "/",
    "/pricing",
    "/about",
    "/product",
    "/docs",
    "/security",
    "/faq",
    "/blog",
)

_TOKEN_LIKE_TEXT = re.compile(
    r"\b(?=[A-Za-z0-9]{20,}\b)(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]+\b"
    r"|\b(?=[A-Za-z0-9·]{20,}\b)(?=[A-Za-z0-9·]*[A-Za-z])(?=[A-Za-z0-9·]*\d)"
    r"[A-Za-z0-9]+(?:·[A-Za-z0-9]+){2,}\b"
)


def _redact_token_like_text(value: str) -> str:
    return _TOKEN_LIKE_TEXT.sub("[redacted token-like text]", value)


class _StructuredTextExtractor(HTMLParser):
    """HTML parser that preserves hierarchy, extracts tables, lists, and semantic blocks."""

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self._in_script_or_style = False
        self._pieces: list[str] = []
        self._current_tag_stack: list[str] = []

        # Structured signal buckets
        self.pricing_signals: list[str] = []
        self.team_signals: list[str] = []
        self.feature_signals: list[str] = []
        self.testimonial_signals: list[str] = []
        self.integration_signals: list[str] = []

        self._in_table = False
        self._current_row: list[str] = []
        self._table_rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        self._current_tag_stack.append(tag_lower)
        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        class_id_str = f"{attr_dict.get('class', '')} {attr_dict.get('id', '')} {attr_dict.get('role', '')}".lower()

        if tag_lower in {"script", "style", "noscript", "svg", "path"}:
            self._in_script_or_style = True
        elif tag_lower == "title":
            self._in_title = True
        elif tag_lower in {"h1", "h2", "h3", "h4"}:
            self._pieces.append("\n\n")
        elif tag_lower in {"p", "div", "section", "article"}:
            if self._pieces and not self._pieces[-1].endswith("\n"):
                self._pieces.append("\n")
        elif tag_lower == "li":
            self._pieces.append("\n• ")
        elif tag_lower == "br":
            self._pieces.append("\n")
        elif tag_lower == "table":
            self._in_table = True
            self._table_rows = []
        elif tag_lower == "tr":
            self._current_row = []

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if self._current_tag_stack and self._current_tag_stack[-1] == tag_lower:
            self._current_tag_stack.pop()
        elif tag_lower in self._current_tag_stack:
            while self._current_tag_stack and self._current_tag_stack[-1] != tag_lower:
                self._current_tag_stack.pop()
            if self._current_tag_stack:
                self._current_tag_stack.pop()

        if tag_lower in {"script", "style", "noscript", "svg", "path"}:
            self._in_script_or_style = False
        elif tag_lower == "title":
            self._in_title = False
        elif tag_lower in {"h1", "h2", "h3", "h4", "p"}:
            self._pieces.append("\n")
        elif tag_lower == "tr" and self._in_table:
            if self._current_row:
                row_str = " | ".join(self._current_row)
                self._table_rows.append(self._current_row)
                self._pieces.append(f"\n[Table Row: {row_str}]\n")
            self._current_row = []
        elif tag_lower == "table":
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._in_script_or_style:
            return

        cleaned = data.strip()
        if not cleaned:
            return

        if self._in_table:
            self._current_row.append(cleaned)

        self._pieces.append(data)

        # Contextual semantic extraction based on content patterns
        text_lower = cleaned.lower()

        # 1. Pricing signals ($49, €99, /mo, /month, /year, tier, starter, pro, enterprise)
        if re.search(r"(\$\d+|\€\d+|£\d+|\bfree\b|\bpro\b|\benterprise\b|\bstarter\b|\bteam\b|/mo\b|/month\b|/yr\b|/year\b|/user\b|/seat\b|billed annually|custom pricing)", text_lower):
            if len(cleaned) <= 300:
                self.pricing_signals.append(cleaned)

        # 2. Team & Founder signals (Founder, CEO, CTO, Co-founder, VP, Lead, Stanford, Google, Meta, YC)
        if re.search(r"\b(founder|co-founder|ceo|cto|cpo|chief executive|chief technology|vp of engineering|head of product|ph\.?d|stanford|mit|berkeley|google|meta|apple|openai|stripe|databricks)\b", text_lower):
            if len(cleaned) <= 300:
                self.team_signals.append(cleaned)

        # 3. Testimonial signals (quotes, customer success, case studies)
        if (cleaned.startswith('"') or cleaned.startswith("“") or "testimonial" in text_lower or "customer story" in text_lower or "case study" in text_lower) and len(cleaned) >= 20:
            if len(cleaned) <= 350:
                self.testimonial_signals.append(cleaned)

        # 4. Integrations signals (integrate with, supported platforms, connectors)
        if re.search(r"\b(integrat(ion|e|es|ed)|connects with|supported connectors|api|slack|salesforce|snowflake|aws|postgres|github|hubspot|jira)\b", text_lower):
            if len(cleaned) <= 250:
                self.integration_signals.append(cleaned)

    def get_text(self) -> str:
        raw = "".join(self._pieces)
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
        # Collapse multiple blank lines into single blank line
        cleaned_lines: list[str] = []
        for line in lines:
            if line:
                cleaned_lines.append(line)
            elif cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
        return "\n".join(cleaned_lines)


def _format_structured_evidence(
    raw_body: str,
    pricing_items: list[str],
    team_items: list[str],
    testimonial_items: list[str],
    integration_items: list[str],
) -> str:
    """Combine structured signal blocks with clean page text for maximum evidence density."""
    sections: list[str] = []

    # Format pricing block if relevant
    if pricing_items:
        unique_pricing = list(dict.fromkeys(pricing_items))[:6]
        pricing_text = " | ".join(unique_pricing)
        sections.append(f"[PRICING & TIERS]: {pricing_text}")

    # Format team block if relevant
    if team_items:
        unique_team = list(dict.fromkeys(team_items))[:6]
        team_text = " • ".join(unique_team)
        sections.append(f"[TEAM & FOUNDERS]: {team_text}")

    # Format testimonial block if relevant
    if testimonial_items:
        unique_test = list(dict.fromkeys(testimonial_items))[:4]
        test_text = " | ".join(unique_test)
        sections.append(f"[CUSTOMER TESTIMONIALS & TRACTION]: {test_text}")

    # Format integrations block if relevant
    if integration_items:
        unique_integ = list(dict.fromkeys(integration_items))[:6]
        integ_text = " • ".join(unique_integ)
        sections.append(f"[INTEGRATIONS & ECOSYSTEM]: {integ_text}")

    # Add general body text
    body_clean = re.sub(r"\s+", " ", raw_body).strip()
    if sections:
        structured_header = "\n".join(sections)
        return f"{structured_header}\n\n{body_clean}".strip()
    return body_clean


def extract_html_text(html_content: str) -> tuple[str, str]:
    """Extract clean title and rich, structured body text from HTML string."""
    parser = _StructuredTextExtractor()
    try:
        parser.feed(html_content)
        title = html.unescape(parser.title).strip()
        title = re.sub(r"\s+", " ", title)
        body = parser.get_text()
        rich_body = _format_structured_evidence(
            body,
            parser.pricing_signals,
            parser.team_signals,
            parser.testimonial_signals,
            parser.integration_signals,
        )
        return title, _redact_token_like_text(rich_body)
    except Exception:
        # Fallback regex extraction
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else ""
        cleaned = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html_content, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", html.unescape(cleaned)).strip()
        return title, _redact_token_like_text(cleaned)


class WebFetchTool:
    """Tool for safe website and document fetching with policy validation."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout: float = 10.0,
        max_bytes: int = 300_000,
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
        """Fetch a page and convert it into a tagged Evidence object with rich excerpt."""
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
            excerpt=text[:2500],
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
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(urls), 8)) as executor:
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
                excerpt=text[:2500],
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
