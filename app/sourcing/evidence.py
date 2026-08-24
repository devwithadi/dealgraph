import json
import os
import re
import subprocess
from collections.abc import Callable

from urllib.parse import urlsplit

from app.core.logging import current_request_id
from app.domain.enums import CitationTag
from app.domain.models import Candidate, Evidence
from app.sourcing.policy import BLOCKED_HOSTS, SourcePolicyError


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
            status=CitationTag.VERIFIED,
            published_at=candidate.launched_at,
        )
    ]


def _allowed_research_url(url: str) -> bool:
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


def agent_reach_evidence(
    candidate: Candidate,
    topic: str,
    start: int,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[Evidence]:
    """Search through Agent Reach's Exa route and normalize its cited results."""
    query = (
        f"Independent current evidence about {candidate.name} ({candidate.website}): "
        f"product, founders, customers, traction, funding, competitors, and risks relevant to {topic}"
    )
    command = [
        "mcporter",
        "call",
        "exa.web_search_exa",
        "--args",
        json.dumps({"query": query, "numResults": 5}),
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
        completed = runner(
            command,
            capture_output=True,
            text=True,
            timeout=35,
            check=False,
            env=allowed_env,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SourcePolicyError("Agent Reach research unavailable") from error
    if completed.returncode != 0:
        raise SourcePolicyError("Agent Reach research failed")
    if len(completed.stdout.encode("utf-8")) > 200_000:
        raise SourcePolicyError("Agent Reach output exceeded 200 KB")

    evidence: list[Evidence] = []
    for block in re.split(r"\n-{3,}\n", completed.stdout):
        title = re.search(r"^Title:\s*(.+)$", block, re.MULTILINE)
        url = re.search(r"^URL:\s*(\S+)$", block, re.MULTILINE)
        highlights = block.partition("Highlights:")[2].strip()
        if not title or not url or not highlights or not _allowed_research_url(url.group(1)):
            continue
        evidence.append(
            Evidence(
                id=f"ev-{start + len(evidence):03d}",
                claim=f"Agent Reach search result: {title.group(1).strip()}",
                excerpt=" ".join(highlights.split())[:1200],
                source_url=url.group(1),
                source_title=title.group(1).strip(),
                source_type="agent_reach",
                trust_tier="open_web",
                verification="third_party_search",
                status=CitationTag.TRUSTED,
            )
        )
    if not evidence:
        raise SourcePolicyError("Agent Reach returned no usable public evidence")
    return evidence
