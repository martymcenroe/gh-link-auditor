"""Sitemap-based same-site page discovery.

When a page 404s but the domain is alive, searches the site's sitemap.xml
for pages that likely match the archived content.

See Issue #106 for specification.
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def fetch_sitemap(domain: str) -> list[str]:
    """Fetch and parse sitemap.xml from a domain.

    Tries common sitemap locations: /sitemap.xml, /sitemap_index.xml.

    Args:
        domain: Domain to fetch sitemap from (e.g. "www.python-httpx.org").

    Returns:
        List of URLs found in the sitemap.
    """
    sitemap_paths = ["/sitemap.xml", "/sitemap_index.xml"]
    urls: list[str] = []

    for path in sitemap_paths:
        sitemap_url = f"https://{domain}{path}"
        content = _fetch_url(sitemap_url)
        if content is None:
            continue

        # Check if this is a sitemap index (contains other sitemaps)
        if "<sitemapindex" in content:
            child_urls = _extract_sitemap_urls(content)
            for child_url in child_urls:
                child_content = _fetch_url(child_url)
                if child_content:
                    urls.extend(_extract_loc_urls(child_content))
        else:
            urls.extend(_extract_loc_urls(content))

        if urls:
            break

    return urls


def search_sitemap_for_match(
    sitemap_urls: list[str],
    original_path: str,
    archive_title: str | None = None,
    max_candidates: int = 5,
) -> list[str]:
    """Search sitemap URLs for pages that likely match the dead page.

    Scoring is based on:
    - Shared path segments with the original URL
    - Slug similarity to the archive title
    - Path depth similarity

    Args:
        sitemap_urls: URLs from the sitemap.
        original_path: Original dead URL path (e.g. "/advanced/").
        archive_title: Title from archive.org snapshot.
        max_candidates: Maximum candidates to return.

    Returns:
        List of candidate URLs, best matches first.
    """
    if not sitemap_urls:
        return []

    original_segments = _path_segments(original_path)
    title_slug = _slugify(archive_title) if archive_title else ""

    scored: list[tuple[float, str]] = []

    for url in sitemap_urls:
        parsed = urlparse(url)
        candidate_path = parsed.path
        candidate_segments = _path_segments(candidate_path)

        score = 0.0

        # Shared path segments (strongest signal)
        shared = set(original_segments) & set(candidate_segments)
        if original_segments:
            score += len(shared) / len(original_segments) * 0.5

        # Title slug appears in candidate path
        if title_slug and title_slug in candidate_path.lower():
            score += 0.3

        # Partial slug match (individual words from title)
        if title_slug:
            title_words = set(title_slug.split("-"))
            path_lower = candidate_path.lower()
            matching_words = sum(1 for w in title_words if w in path_lower and len(w) > 2)
            if title_words:
                score += (matching_words / len(title_words)) * 0.2

        # Skip exact original path (it's the dead one)
        if candidate_path.rstrip("/") == original_path.rstrip("/"):
            continue

        if score > 0:
            scored.append((score, url))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [url for _, url in scored[:max_candidates]]


def _fetch_url(url: str) -> str | None:
    """Fetch URL content as string.

    Args:
        url: URL to fetch.

    Returns:
        Content string, or None on failure.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "gh-link-auditor/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def _extract_loc_urls(xml_content: str) -> list[str]:
    """Extract <loc> URLs from sitemap XML.

    Args:
        xml_content: Sitemap XML string.

    Returns:
        List of URLs found in <loc> tags.
    """
    return re.findall(r"<loc>(.*?)</loc>", xml_content)


def _extract_sitemap_urls(xml_content: str) -> list[str]:
    """Extract child sitemap URLs from a sitemap index.

    Args:
        xml_content: Sitemap index XML string.

    Returns:
        List of child sitemap URLs.
    """
    return re.findall(r"<loc>(.*?)</loc>", xml_content)


def _path_segments(path: str) -> list[str]:
    """Split a URL path into non-empty segments.

    Args:
        path: URL path (e.g. "/docs/advanced/usage").

    Returns:
        List of path segments (e.g. ["docs", "advanced", "usage"]).
    """
    return [s for s in path.strip("/").split("/") if s]


def _slugify(text: str) -> str:
    """Convert text to a URL-friendly slug.

    Args:
        text: Text to slugify.

    Returns:
        Lowercased, hyphen-separated slug.
    """
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")
