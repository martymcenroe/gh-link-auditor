"""Content similarity signal for Slant scoring engine.

Fetches the candidate page, strips HTML, and compares to the
archived plain-text content using SequenceMatcher.

Weight: 20 points.

See LLD #21 §2.5 "Content Similarity Signal Flow" for specification.
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
            # Limit to 1MB to prevent resource exhaustion (LLD §7.2)
            data = resp.read(1_048_576)
            return data.decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError):
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def strip_html(html: str) -> str:
    """Remove HTML tags and return plain text.

    Strips script/style blocks first, then all remaining tags.

    Args:
        html: HTML string.

    Returns:
        Plain text with tags removed.
    """
    if not html:
        return ""

    # Remove script and style blocks
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    # Remove all remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compare_content(candidate_url: str, archived_content: str, timeout: float = 10.0) -> float:
    """Fetch candidate page, strip HTML, compare to archived content.

    Args:
        candidate_url: URL of candidate page to fetch.
        archived_content: Plain text from archived version.
        timeout: HTTP request timeout in seconds.

    Returns:
        Similarity ratio 0.0–1.0. Returns 0.0 on error or empty inputs.
    """
    if not archived_content:
        return 0.0

    try:
        html = _fetch_page(candidate_url, timeout=timeout)
        if html is None:
            return 0.0

        candidate_text = strip_html(html)
        if not candidate_text:
            return 0.0

        return SequenceMatcher(None, archived_content.lower(), candidate_text.lower()).ratio()
    except Exception:
        return 0.0
