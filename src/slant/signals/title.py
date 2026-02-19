"""Title fuzzy match signal for Slant scoring engine.

Fetches the candidate page, extracts its <title>, and compares
to the archived title using SequenceMatcher.

Weight: 25 points.

See LLD #21 §2.5 "Title Match Signal Flow" for specification.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from difflib import SequenceMatcher

# ---------------------------------------------------------------------------
# Internal HTTP helper (mock target for testing)
# ---------------------------------------------------------------------------


def _fetch_page(url: str, *, timeout: float = 10.0) -> str | None:
    """Fetch page HTML content.

    Args:
        url: URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        HTML string, or None on failure.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "gh-link-auditor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError):
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_title(html: str) -> str | None:
    """Extract <title> text from HTML.

    Args:
        html: HTML string.

    Returns:
        Title text, or None if not found or empty.
    """
    if not html:
        return None

    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        text = match.group(1).strip()
        text = re.sub(r"\s+", " ", text)
        return text if text else None
    return None


def match_title(candidate_url: str, archived_title: str, timeout: float = 10.0) -> float:
    """Fetch candidate page title and compare to archived title.

    Args:
        candidate_url: URL of candidate page to fetch.
        archived_title: Title from archived version of dead page.
        timeout: HTTP request timeout in seconds.

    Returns:
        Similarity ratio 0.0–1.0. Returns 0.0 on error or empty inputs.
    """
    if not archived_title:
        return 0.0

    html = _fetch_page(candidate_url, timeout=timeout)
    if html is None:
        return 0.0

    candidate_title = extract_title(html)
    if candidate_title is None:
        return 0.0

    # Normalize both for comparison
    a = archived_title.lower().strip()
    b = candidate_title.lower().strip()
    return SequenceMatcher(None, a, b).ratio()
