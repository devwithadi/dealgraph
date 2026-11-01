import json
import os
import re
import subprocess
from collections.abc import Callable
from urllib.parse import urlsplit

from app.core.logging import current_request_id
from app.core.urls import resolve_host
from app.domain.enums import CitationTag
from app.domain.models import Candidate, Evidence
from app.sourcing.policy import SourcePolicyError, validate_public_url


def candidate_evidence(candidate: Candidate) -> list[Evidence]:
    """Build baseline evidence without upgrading a non-YC source to YC-verified."""
    facts = [candidate.one_liner, candidate.description]
    if candidate.team_size is not None:
        facts.append(f"Reported team size: {candidate.team_size}.")
    if candidate.is_hiring:
        facts.append("YC marks the company as hiring.")
    source_host = (urlsplit(candidate.source_url).hostname or "").lower()
    if source_host == "news.ycombinator.com":
        source_name, source_type, trust_tier, verification, status = (
            "Hacker News launch",
            "hacker_news",
            "public_community",
            "third_party",
            CitationTag.TRUSTED,
        )
    elif source_host == "ycombinator.com" or source_host.endswith(".ycombinator.com"):
        source_name, source_type, trust_tier, verification, status = (
            "YC profile",
            "yc_directory",
            "curated_directory",
            "third_party",
            CitationTag.VERIFIED,
        )
    elif source_host == "producthunt.com" or source_host.endswith(".producthunt.com"):
        source_name, source_type, trust_tier, verification, status = (
            "Product Hunt launch",
            "product_hunt",
            "product_community",
            "third_party",
            CitationTag.TRUSTED,
        )
    else:
        source_name, source_type, trust_tier, verification, status = (
            "Candidate source",
            "candidate_source",
            "unverified_origin",
            "source_record",
            CitationTag.CLAIMED,
        )
    return [
        Evidence(
            id="ev-001",
            claim=source_name,
            excerpt=" ".join(filter(None, facts))[:2500],
            source_url=candidate.source_url,
            source_title=f"{source_name}: {candidate.name}",
            source_type=source_type,
            trust_tier=trust_tier,
            verification=verification,
            status=status,
            published_at=candidate.launched_at,
        )
    ]


def _allowed_research_url(
    url: str, resolver: Callable[[str], list[str]] = resolve_host
) -> bool:
    try:
        validate_public_url(url, resolver=resolver)
    except SourcePolicyError:
        return False
    return True


def agent_reach_evidence(
    candidate: Candidate,
    topic: str,
    start: int,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    resolver: Callable[[str], list[str]] = resolve_host,
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
        if not title or not url or not highlights or not _allowed_research_url(url.group(1), resolver):
            continue
        evidence.append(
            Evidence(
                id=f"ev-{start + len(evidence):03d}",
                claim=f"Agent Reach search result: {title.group(1).strip()}",
                excerpt=" ".join(highlights.split())[:2500],
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
