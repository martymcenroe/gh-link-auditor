"""URL path similarity signal for Slant scoring engine.

Compares the path components of the dead and candidate URLs
using SequenceMatcher on the normalized path strings.

Weight: 10 points.

See LLD #21 §2.4 for specification.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from urllib.parse import urlparse


def compare_url_paths(dead_url: str, candidate_url: str) -> float:
    """Compare URL path components of dead and candidate URLs.

    Normalizes paths by stripping trailing slashes and lowercasing
    before comparison.

    Args:
        dead_url: The original dead URL.
        candidate_url: The candidate replacement URL.

    Returns:
        Similarity ratio 0.0–1.0 for path components.
    """
    dead_path = urlparse(dead_url).path.rstrip("/").lower() or "/"
    candidate_path = urlparse(candidate_url).path.rstrip("/").lower() or "/"
    return SequenceMatcher(None, dead_path, candidate_path).ratio()
