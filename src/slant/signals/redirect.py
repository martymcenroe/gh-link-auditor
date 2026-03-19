"""Redirect detection signal for Slant scoring engine.

Checks if the dead URL redirects to the candidate URL via HTTP 3xx.
Returns 1.0 if the redirect chain reaches the candidate, 0.0 otherwise.

Weight: 40 points (highest signal).

See LLD #21 §2.5 "Redirect Signal Flow" for specification.
"""

from __future__ import annotations

import urllib.error
import urllib.request

_REDIRECT_CODES = {301, 302, 303, 307, 308}
_MAX_HOPS = 5


# ---------------------------------------------------------------------------
# Internal HTTP helper (mock target for testing)
# ---------------------------------------------------------------------------


def _http_get(url: str, *, timeout: float = 10.0) -> dict:
    """Make a GET request without following redirects.

    Args:
        url: URL to request.
        timeout: Request timeout in seconds.

    Returns:
        Dict with ``status_code`` (int | None) and ``location`` (str | None).
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "gh-link-auditor/1.0"})

        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirectHandler)
        resp = opener.open(req, timeout=timeout)
        return {"status_code": resp.status, "location": resp.headers.get("Location")}
    except urllib.error.HTTPError as e:
        return {"status_code": e.code, "location": e.headers.get("Location")}
    except (urllib.error.URLError, OSError):
        return {"status_code": None, "location": None}


def _normalize_url(url: str) -> str:
    """Normalize URL for comparison (strip trailing slash, lowercase)."""
    return url.rstrip("/").lower()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_redirect(
    dead_url: str,
    candidate_url: str,
    timeout: float = 10.0,
    candidate_source: str = "",
) -> float:
    """Check if dead URL redirects to candidate via HTTP 3xx chain.

    If the candidate was already discovered via redirect chain (source
    is "redirect_chain"), returns 1.0 immediately — N2 already verified it.

    Otherwise follows up to 5 redirect hops. Returns 1.0 if the chain
    reaches the candidate URL (normalized), 0.0 otherwise.

    Args:
        dead_url: The dead URL to check.
        candidate_url: The candidate replacement URL.
        timeout: HTTP request timeout in seconds.
        candidate_source: How the candidate was discovered (e.g., "redirect_chain").

    Returns:
        1.0 if redirect reaches candidate, 0.0 otherwise.
    """
    if candidate_source == "redirect_chain":
        return 1.0
    try:
        current = dead_url
        visited: set[str] = set()
        candidate_normalized = _normalize_url(candidate_url)

        for _ in range(_MAX_HOPS):
            if current in visited:
                return 0.0
            visited.add(current)

            result = _http_get(current, timeout=timeout)
            status = result["status_code"]
            location = result["location"]

            if status in _REDIRECT_CODES and location:
                if _normalize_url(location) == candidate_normalized:
                    return 1.0
                current = location
                continue

            return 0.0

        return 0.0
    except Exception:
        return 0.0
