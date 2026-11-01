from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from collections.abc import Callable
from urllib.parse import urlsplit

from app.analysis.diligence.models import SearchQuery
from app.core.logging import current_request_id
from app.domain.enums import CitationTag
from app.domain.models import Candidate, Evidence
from app.sourcing.policy import BLOCKED_HOSTS

LOGGER = logging.getLogger("dealgraph.diligence.search")

VERIFIED_DOMAINS = {
    "sec.gov",
    "uspto.gov",
    "companieshouse.gov.uk",
    "ycombinator.com",
}


def is_allowed_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    blocked = any(host == item or host.endswith(f".{item}") for item in BLOCKED_HOSTS)
    try:
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme in {"http", "https"}
        and host
        and not parsed.username
        and not parsed.password
        and port in {None, 80, 443}
        and not blocked
    )


def _resolve_status_for_url(url: str) -> CitationTag:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if any(host == d or host.endswith(f".{d}") for d in VERIFIED_DOMAINS):
        return CitationTag.VERIFIED
    return CitationTag.TRUSTED


def _parse_search_output(stdout: str, query_item: SearchQuery, start_id: int) -> list[Evidence]:
    evidence: list[Evidence] = []
    for block in re.split(r"\n-{3,}\n", stdout):
        title_match = re.search(r"^Title:\s*(.+)$", block, re.MULTILINE)
        url_match = re.search(r"^URL:\s*(\S+)$", block, re.MULTILINE)
        highlights = block.partition("Highlights:")[2].strip()
        if not title_match or not url_match or not highlights:
            continue
        url = url_match.group(1).strip()
        if not is_allowed_url(url):
            continue
        title = title_match.group(1).strip()
        status = _resolve_status_for_url(url)
        evidence.append(
            Evidence(
                id=f"ev-{start_id + len(evidence):03d}",
                claim=f"[{query_item.pillar}] {title}",
                excerpt=" ".join(highlights.split())[:1200],
                source_url=url,
                source_title=title,
                source_type="deep_diligence_search",
                trust_tier="multi_hop_web",
                verification="multi_hop_search",
                status=status,
            )
        )
    return evidence


class SearchTool:
    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        custom_search_fn: Callable[[Candidate, SearchQuery, int], list[Evidence]] | None = None,
    ) -> None:
        self.runner = runner
        self.custom_search_fn = custom_search_fn

    def search(
        self,
        candidate: Candidate,
        query_item: SearchQuery,
        start_id: int,
        *,
        num_results: int = 5,
    ) -> list[Evidence]:
        """Execute search for a candidate query across diligence pillars."""
        if self.custom_search_fn is not None:
            return self.custom_search_fn(candidate, query_item, start_id)

        command = [
            "mcporter",
            "call",
            "exa.web_search_exa",
            "--args",
            json.dumps({"query": query_item.query, "numResults": num_results}),
            "--output",
            "text",
            "--timeout",
            "30000",
        ]
        allowed_env = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "USER", "TMPDIR", "XDG_CONFIG_HOME", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY")
            if key in os.environ
        }
        allowed_env["DEALGRAPH_REQUEST_ID"] = current_request_id()

        try:
            completed = self.runner(
                command,
                capture_output=True,
                text=True,
                timeout=35,
                check=False,
                env=allowed_env,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            LOGGER.warning("Search subprocess failed query=%r error=%s", query_item.query, error)
            return []

        if completed.returncode != 0 or len(completed.stdout.encode("utf-8")) > 200_000:
            return []

        return _parse_search_output(completed.stdout, query_item, start_id)
