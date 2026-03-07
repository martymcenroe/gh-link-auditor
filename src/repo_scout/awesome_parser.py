"""Awesome list parser.

Fetches and parses Awesome list markdown files for GitHub repo links.

See LLD #3 §2.4 for awesome_parser specification.
"""

from __future__ import annotations

import logging
import re

import httpx

from repo_scout.models import DiscoverySource, RepositoryRecord, make_repo_record

logger = logging.getLogger(__name__)

_GITHUB_LINK_RE = re.compile(r"\[([^\]]*)\]\((https://github\.com/([^/\s]+)/([^/\s\)#]+))[^\)]*\)")

_SECTION_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

_GITHUB_URL_RE = re.compile(r"^https?://github\.com/([^/]+)/([^/?#]+?)(?:\.git)?/?$")


def normalize_github_url(url: str) -> tuple[str, str] | None:
    """Normalize a GitHub URL to (owner, repo).

    Args:
        url: A GitHub URL to normalize.

    Returns:
        Tuple of (owner, repo) or None if not a valid repo URL.
    """
    match = _GITHUB_URL_RE.match(url.strip())
    if not match:
        return None

    owner = match.group(1)
    repo = match.group(2)

    # Filter out non-repo pages
    if owner in ("features", "pricing", "about", "explore", "topics", "settings"):
        return None

    return (owner, repo)


def extract_github_links(
    markdown_content: str,
) -> list[tuple[str, str, str | None]]:
    """Extract GitHub repo links from markdown content.

    Args:
        markdown_content: Raw markdown text.

    Returns:
        List of (url, link_text, section) tuples.
    """
    # Find all section headings with their positions
    sections: list[tuple[int, str]] = []
    for match in _SECTION_RE.finditer(markdown_content):
        sections.append((match.start(), match.group(2).strip()))

    results: list[tuple[str, str, str | None]] = []
    for match in _GITHUB_LINK_RE.finditer(markdown_content):
        link_text = match.group(1)
        url = match.group(2)
        pos = match.start()

        # Find the most recent section heading before this link
        current_section = None
        for sec_pos, sec_name in sections:
            if sec_pos < pos:
                current_section = sec_name
            else:
                break

        results.append((url, link_text, current_section))

    return results


def _fetch_markdown(url: str) -> str:
    """Fetch raw markdown content from a URL.

    For GitHub repos, fetches the raw README.

    Args:
        url: URL to fetch.

    Returns:
        Markdown content string.
    """
    # Convert GitHub repo URL to raw README URL
    normalized = normalize_github_url(url)
    if normalized:
        owner, repo = normalized
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md"
    else:
        raw_url = url

    try:
        response = httpx.get(raw_url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        return response.text
    except httpx.HTTPError:
        logger.exception("Failed to fetch %s", raw_url)
        return ""


def parse_awesome_list(url: str) -> list[RepositoryRecord]:
    """Fetch and parse an Awesome list for GitHub repo links.

    Args:
        url: URL of the Awesome list repository.

    Returns:
        List of RepositoryRecords found.
    """
    markdown = _fetch_markdown(url)
    if not markdown:
        return []

    links = extract_github_links(markdown)
    records: list[RepositoryRecord] = []
    seen: set[str] = set()

    for link_url, link_text, section in links:
        normalized = normalize_github_url(link_url)
        if not normalized:
            continue

        owner, repo = normalized
        full_name = f"{owner}/{repo}"
        if full_name in seen:
            continue
        seen.add(full_name)

        metadata: dict = {"source_url": url}
        if section:
            metadata["section"] = section
        if link_text:
            metadata["link_text"] = link_text

        records.append(
            make_repo_record(
                owner=owner,
                name=repo,
                source=DiscoverySource.AWESOME_LIST,
                metadata=metadata,
            )
        )

    return records
