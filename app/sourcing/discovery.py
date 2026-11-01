from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from app.core.logging import current_request_id
from app.domain.models import Candidate
from app.sourcing.constants import AGENT_REACH, AgentReachDirectorySource
from app.sourcing.policy import validate_public_url

LOGGER = logging.getLogger("dealgraph.sourcing.discovery")

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"
AGGREGATOR_DOMAINS = {
    "ycombinator.com",
    "news.ycombinator.com",
    "producthunt.com",
    "twitter.com",
    "x.com",
    "github.com",
    "techcrunch.com",
    "medium.com",
    "substack.com",
    "youtube.com",
    "reddit.com",
} | set(AGENT_REACH.directory_hosts)


def _is_aggregator_host(host: str) -> bool:
    return host in AGGREGATOR_DOMAINS or any(host.endswith(f".{domain}") for domain in AGGREGATOR_DOMAINS)


def _directory_source_for_host(host: str) -> AgentReachDirectorySource | None:
    for source in AGENT_REACH.directory_sources:
        if host == source.host or host.endswith(f".{source.host}"):
            return source
    return None


def make_candidate_slug(name_or_domain: str) -> str:
    """Generate a valid, normalized slug for a candidate conforming to ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$."""
    cleaned = re.sub(r"^https?://(www\.)?", "", name_or_domain.lower())
    cleaned = cleaned.split("/")[0].split("?")[0].strip()
    slug = re.sub(r"[^a-z0-9._-]+", "-", cleaned).strip(".-_")
    if not slug:
        slug = "startup"
    elif not slug[0].isalnum():
        slug = f"c-{slug}".strip(".-_")
    return slug[:128]


def normalize_domain(url_or_slug: str) -> str:
    """Extract normalized domain name or slug for candidate deduplication."""
    if not url_or_slug:
        return ""
    if "://" in url_or_slug:
        parsed = urlsplit(url_or_slug)
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host or make_candidate_slug(url_or_slug)
    host = url_or_slug.lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host


def clean_startup_name(raw_title: str) -> tuple[str, str]:
    """Extract clean startup name and one-liner description from post titles."""
    title = raw_title.strip()
    # Strip prefixes like Show HN, Launch HN, Ask HN, etc.
    title = re.sub(r"^(Show\s+HN|Launch\s+HN|Ask\s+HN|Tell\s+HN)\s*[:–—-]?\s*", "", title, flags=re.IGNORECASE)
    # Strip Product Hunt suffixes
    title = re.sub(r"\s*\|\s*Product\s*Hunt\s*$", "", title, flags=re.IGNORECASE)
    # Strip YC suffixes
    title = re.sub(r"\s*\((?:YC\s*)?[WS]\d{2}\)\s*$", "", title, flags=re.IGNORECASE)

    # Split by common separators (–, -, :, |, —)
    parts = re.split(r"\s*[:–—|]\s*|\s+-\s+", title, maxsplit=1)
    if len(parts) == 2:
        name, one_liner = parts[0].strip(), parts[1].strip()
    else:
        # Check if first 1-3 words look like a name
        words = title.split()
        if len(words) <= 3:
            name = title
            one_liner = title
        else:
            name = " ".join(words[:2])
            one_liner = title

    name = re.sub(r"[^\w\s.-]", "", name).strip()
    if not name or len(name) > 60:
        name = title[:40].strip()
    return name, one_liner


def extract_website_from_text(text: str, fallback_domain: str = "") -> str:
    """Extract the first valid non-aggregator company website from text/snippets."""
    urls = re.findall(r"https?://[a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s,;)\"'>]*)?", text)
    for url in urls:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if host and not _is_aggregator_host(host):
            # Clean trailing punctuation
            clean_url = url.rstrip(".,;)\"'>")
            return f"{parsed.scheme}://{parsed.netloc}"
    if fallback_domain and "." in fallback_domain and fallback_domain not in AGGREGATOR_DOMAINS:
        return f"https://{fallback_domain}"
    return ""


def fetch_hn_candidates(
    topic: str,
    client: httpx.Client | None = None,
    *,
    limit: int = AGENT_REACH.discovery_candidate_limit,
) -> list[Candidate]:
    """Source candidate startups from Hacker News Show HN launches using the public Algolia API."""
    candidates: list[Candidate] = []
    http_client = client or httpx.Client(timeout=httpx.Timeout(10, connect=5))
    try:
        response = http_client.get(
            HN_SEARCH_URL,
            params={
                "query": topic,
                "tags": "show_hn",
                "hitsPerPage": min(limit * 2, 40),
            },
        )
        if response.status_code != 200:
            LOGGER.warning("HN API returned status=%d for topic=%r", response.status_code, topic)
            return []
        data = response.json()
    except Exception as error:
        LOGGER.warning("HN candidate sourcing failed topic=%r error=%s", topic, error)
        return []

    hits = data.get("hits", [])
    for hit in hits:
        raw_title = str(hit.get("title") or "").strip()
        if not raw_title:
            continue

        name, one_liner = clean_startup_name(raw_title)
        points = int(hit.get("points") or 0)
        num_comments = int(hit.get("num_comments") or 0)
        author = str(hit.get("author") or "")
        created_at_str = hit.get("created_at")
        story_url = str(hit.get("url") or "")
        story_text = str(hit.get("story_text") or "")
        object_id = str(hit.get("objectID") or "")
        hn_item_url = f"https://news.ycombinator.com/item?id={object_id}"

        # Resolve website
        website = ""
        story_host = normalize_domain(story_url)
        if story_url and story_host and not _is_aggregator_host(story_host):
            parsed_story = urlsplit(story_url)
            website = f"{parsed_story.scheme}://{parsed_story.netloc}"
        if not website and story_text:
            website = extract_website_from_text(story_text)

        launched_at: datetime | None = None
        if created_at_str:
            try:
                launched_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            except Exception:
                launched_at = None

        traction_desc = f"Traction: Show HN launch with {points} points and {num_comments} comments."
        founder_signal = f" Founder: @{author} on Hacker News." if author else ""
        long_desc = f"{one_liner}. {traction_desc}{founder_signal}"

        slug = make_candidate_slug(normalize_domain(website) or name)
        candidate = Candidate(
            slug=slug,
            name=name,
            website=website,
            one_liner=one_liner[:180],
            description=long_desc[:600],
            batch="Show HN",
            industry=topic.title(),
            tags=["Hacker News", "Show HN", "AI", "Startup"],
            team_size=None,
            launched_at=launched_at,
            is_hiring=bool("hiring" in story_text.lower() or "hiring" in one_liner.lower()),
            source_url=hn_item_url,
        )
        candidates.append(candidate)
        if len(candidates) >= limit:
            break

    LOGGER.info("sourced %d candidates from Hacker News Show HN topic=%r", len(candidates), topic)
    return candidates


def search_agent_reach_candidates(
    topic: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    structured_output: Callable[[str], Mapping[str, object]] | None = None,
    limit: int = AGENT_REACH.discovery_candidate_limit,
) -> list[Candidate]:
    """Source candidate startups across Product Hunt, TechCrunch, and web via Agent Reach / Exa."""
    directory_filters = " OR ".join(AGENT_REACH.directory_site_filters)
    query = (
        f"Promising new startup products and launches for {topic}: "
        f"site:producthunt.com/products OR site:news.ycombinator.com/item OR site:techcrunch.com OR "
        f"{directory_filters} "
        f"product name, official website, founders, launch, and funding"
    )
    command = [
        "mcporter",
        "call",
        "exa.web_search_exa",
        "--args",
        json.dumps({"query": query, "numResults": min(limit * 2, AGENT_REACH.discovery_max_search_results)}),
        "--output",
        "text",
        "--timeout",
        str(AGENT_REACH.mcporter_timeout_milliseconds),
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
            timeout=AGENT_REACH.subprocess_timeout_seconds,
            check=False,
            env=allowed_env,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        LOGGER.warning("Agent Reach candidate discovery subprocess failed error=%s", error)
        return []

    if completed.returncode != 0 or not completed.stdout:
        return []
    if len(completed.stdout.encode("utf-8")) > AGENT_REACH.max_output_bytes:
        LOGGER.warning("Agent Reach candidate discovery output exceeded 200 KB")
        return []

    if structured_output is not None:
        try:
            payload = structured_output(completed.stdout)
            raw_candidates = payload.get("candidates")
            if not isinstance(raw_candidates, list):
                raise ValueError("discovery response must contain a candidates array")
            candidates = []
            for item in raw_candidates[:limit]:
                if not isinstance(item, dict):
                    continue
                candidate = Candidate.model_validate(item)
                website_host = normalize_domain(candidate.website)
                website = (
                    validate_public_url(candidate.website)
                    if candidate.website and not _is_aggregator_host(website_host)
                    else ""
                )
                candidates.append(
                    candidate.model_copy(
                        update={
                            "website": website,
                            "source_url": validate_public_url(candidate.source_url),
                        }
                    )
                )
            if not candidates:
                raise ValueError("discovery response contained no valid candidates")
            LOGGER.info("sourced %d structured candidates from Agent Reach topic=%r", len(candidates), topic)
            return candidates
        except Exception as error:
            LOGGER.warning("Agent Reach structured discovery failed topic=%r error=%s", topic, error)

    candidates: list[Candidate] = []
    for block in re.split(r"\n-{3,}\n", completed.stdout):
        title_match = re.search(r"^Title:\s*(.+)$", block, re.MULTILINE)
        url_match = re.search(r"^URL:\s*(\S+)$", block, re.MULTILINE)
        highlights = block.partition("Highlights:")[2].strip()
        if not title_match or not url_match:
            continue

        raw_title = title_match.group(1).strip()
        source_url = url_match.group(1).strip()
        name, one_liner = clean_startup_name(raw_title)

        # Extract company website
        parsed_source = urlsplit(source_url)
        source_host = (parsed_source.hostname or "").lower()
        if source_host.startswith("www."):
            source_host = source_host[4:]

        website = ""
        if not _is_aggregator_host(source_host):
            website = f"{parsed_source.scheme}://{parsed_source.netloc}"
        elif highlights:
            website = extract_website_from_text(highlights)

        # Determine origin source
        batch = AGENT_REACH.default_batch
        tags = list(AGENT_REACH.default_tags)
        if "producthunt.com" in source_url:
            batch = AGENT_REACH.product_hunt_batch
            tags.append("Product Hunt")
        elif "ycombinator.com" in source_url:
            batch = "Hacker News"
            tags.append("Hacker News")
        elif "techcrunch.com" in source_url:
            batch = AGENT_REACH.techcrunch_batch
            tags.append("TechCrunch")
        else:
            directory_source = _directory_source_for_host(source_host)
            if directory_source is not None:
                batch = directory_source.batch
                tags.append(directory_source.tag)

        is_hiring = bool("hiring" in highlights.lower() or "join our team" in highlights.lower())
        long_desc = f"{one_liner}. {highlights[:AGENT_REACH.highlight_max_characters]}".strip()

        slug = make_candidate_slug(normalize_domain(website) or name)
        candidate = Candidate(
            slug=slug,
            name=name,
            website=website,
            one_liner=one_liner[:180],
            description=long_desc[:600],
            batch=batch,
            industry=topic.title(),
            tags=tags,
            team_size=None,
            launched_at=datetime.now(timezone.utc),
            is_hiring=is_hiring,
            source_url=source_url,
        )
        candidates.append(candidate)
        if len(candidates) >= limit:
            break

    LOGGER.info("sourced %d candidates from Agent Reach discovery topic=%r", len(candidates), topic)
    return candidates


def parse_url_seed_candidates(lines_or_data: list[str] | list[dict]) -> list[Candidate]:
    """Parse candidate startups from a seed list of URLs or structured objects."""
    candidates: list[Candidate] = []
    for item in lines_or_data:
        if isinstance(item, dict):
            name = str(item.get("name") or "")
            website = str(item.get("website") or item.get("url") or "")
            if not name and website:
                name = normalize_domain(website).split(".")[0].title()
            if not name:
                continue
            slug = make_candidate_slug(str(item.get("slug") or normalize_domain(website) or name))
            candidate = Candidate(
                slug=slug,
                name=name,
                website=website,
                one_liner=str(item.get("one_liner") or item.get("description") or f"Seed candidate {name}"),
                description=str(item.get("description") or item.get("long_description") or ""),
                batch=str(item.get("batch") or "Seed List"),
                industry=str(item.get("industry") or "Technology"),
                tags=[str(t) for t in item.get("tags") or ["Seed URL"]],
                team_size=item.get("team_size"),
                launched_at=datetime.now(timezone.utc),
                is_hiring=bool(item.get("is_hiring") or item.get("isHiring")),
                source_url=website or "https://dealgraph.internal/seed",
            )
            candidates.append(candidate)
        elif isinstance(item, str):
            line = item.strip()
            if not line or line.startswith("#"):
                continue
            if "://" not in line and "." in line:
                url = f"https://{line}"
            else:
                url = line
            domain = normalize_domain(url)
            name = domain.split(".")[0].title()
            slug = make_candidate_slug(domain or name)
            candidate = Candidate(
                slug=slug,
                name=name,
                website=url,
                one_liner=f"Seed startup at {domain}",
                description=f"Candidate sourced from direct URL seed: {url}",
                batch="URL Seed",
                industry="Technology",
                tags=["URL Seed"],
                team_size=None,
                launched_at=datetime.now(timezone.utc),
                is_hiring=False,
                source_url=url,
            )
            candidates.append(candidate)
    return candidates


def deduplicate_and_merge_candidates(
    candidates: list[Candidate],
    *,
    limit: int | None = None,
) -> list[Candidate]:
    """Deduplicate candidates by domain/slug and merge multi-source signals."""
    seen: dict[str, Candidate] = {}

    for cand in candidates:
        domain = normalize_domain(cand.website) or cand.slug.lower()
        if not domain:
            continue

        if domain not in seen:
            seen[domain] = cand
        else:
            existing = seen[domain]
            # Merge signals
            merged_name = existing.name if len(existing.name) <= len(cand.name) else cand.name
            merged_website = existing.website or cand.website
            # Keep richer one_liner and description
            merged_one_liner = existing.one_liner if len(existing.one_liner) >= len(cand.one_liner) else cand.one_liner
            merged_desc = existing.description
            if cand.description and cand.description not in merged_desc:
                merged_desc = f"{merged_desc} | {cand.description}".strip(" |")

            # Merge tags
            combined_tags = list(dict.fromkeys(existing.tags + cand.tags))
            # Merge team_size & hiring
            merged_team_size = existing.team_size or cand.team_size
            merged_is_hiring = existing.is_hiring or cand.is_hiring
            # Prefer YC / structured batch if present
            merged_batch = existing.batch or cand.batch
            if "summer" in cand.batch.lower() or "winter" in cand.batch.lower() or "yc" in cand.batch.lower():
                merged_batch = cand.batch
            merged_source_url = existing.source_url or cand.source_url
            merged_launched_at = existing.launched_at or cand.launched_at

            seen[domain] = Candidate(
                slug=existing.slug,
                name=merged_name,
                website=merged_website,
                one_liner=merged_one_liner,
                description=merged_desc,
                batch=merged_batch,
                industry=existing.industry or cand.industry,
                tags=combined_tags,
                team_size=merged_team_size,
                launched_at=merged_launched_at,
                is_hiring=merged_is_hiring,
                source_url=merged_source_url,
            )

    merged_list = list(seen.values())
    if limit is not None and limit > 0:
        return merged_list[:limit]
    return merged_list
