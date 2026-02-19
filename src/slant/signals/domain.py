"""Domain match signal for Slant scoring engine.

Compares the domains of the dead and candidate URLs.
Returns 1.0 for exact match (after www normalization), 0.0 otherwise.

Weight: 5 points.

See LLD #21 §2.4 for specification.
"""

from __future__ import annotations

from urllib.parse import urlparse


def _normalize_domain(hostname: str) -> str:
    """Normalize domain by lowercasing and stripping leading www."""
    h = hostname.lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def match_domain(dead_url: str, candidate_url: str) -> float:
    """Compare domains of dead and candidate URLs.

    Normalizes by stripping 'www.' prefix and lowercasing.

    Args:
        dead_url: The original dead URL.
        candidate_url: The candidate replacement URL.

    Returns:
        1.0 for exact domain match, 0.0 otherwise.
    """
    dead_host = urlparse(dead_url).hostname or ""
    candidate_host = urlparse(candidate_url).hostname or ""

    if not dead_host or not candidate_host:
        return 0.0

    return 1.0 if _normalize_domain(dead_host) == _normalize_domain(candidate_host) else 0.0
