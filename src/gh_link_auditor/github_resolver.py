"""GitHub API resolver for detecting repo renames and transfers.

Queries the GitHub REST API to detect 301 redirects for renamed or
transferred repositories, and reconstructs file URLs under the new location.

See LLD #20 §2.4 for API specification. LLD-257 routes all API calls through
``GitHubRateLimitedClient`` so concurrent callers (bulk-scan Stage 3 with
``--workers 32``) share quota accounting and respect 403/429 backoff.
"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

from src.logging_config import setup_logging

if TYPE_CHECKING:
    from gh_link_auditor.bulk_scan.gh_client import GitHubRateLimitedClient

logger = setup_logging("github_resolver")


# ---------------------------------------------------------------------------
# Module-level lazy default client (#257)
# ---------------------------------------------------------------------------

_default_client: GitHubRateLimitedClient | None = None
_default_client_lock = threading.Lock()


def _get_default_client() -> GitHubRateLimitedClient:
    """Return the module-level default client, constructing it on first call.

    Double-checked locking: Stage 3 worker threads can race the first
    ``resolve_repo_redirect``; we don't want two clients each holding their
    own quota counters. Imports of ``bulk_scan.gh_client`` and ``auth`` are
    deferred to inside this function to avoid module-load circularity
    (``bulk_scan.runner`` transitively imports ``link_detective`` which
    imports this module).
    """
    global _default_client
    if _default_client is not None:
        return _default_client
    with _default_client_lock:
        if _default_client is None:
            from gh_link_auditor.auth import resolve_github_token
            from gh_link_auditor.bulk_scan.gh_client import GitHubRateLimitedClient

            token = resolve_github_token() or None
            _default_client = GitHubRateLimitedClient(token=token)
    return _default_client


# ---------------------------------------------------------------------------
# Internal API helper (mock target for testing)
# ---------------------------------------------------------------------------


def _github_api_get(
    url: str,
    token: str | None = None,  # noqa: ARG001 — retained for backwards compat; the client carries its own token
    client: Any | None = None,
) -> dict | None:
    """Make a GET request to the GitHub API via the rate-limited client.

    Args:
        url: GitHub API endpoint URL.
        token: Retained for backwards compatibility. Ignored — the active
               client carries its own token (default uses ``resolve_github_token``).
        client: Optional rate-limited client. When None, the module-level
               default is used (constructed lazily on first call).

    Returns:
        Parsed JSON response dict, or None on 404 / non-2xx / transport error /
        non-JSON body.
    """
    active = client if client is not None else _get_default_client()
    try:
        # #264 — must follow 301s. urllib (pre-#257) did so by default;
        # httpx.Client does NOT, which silently broke GitHub's
        # repo-renamed-to-new-owner detection by returning the 301
        # response body (which has no full_name) instead of the followed
        # target.
        r = active.get(url, follow_redirects=True)
    except httpx.HTTPError:
        logger.warning("GitHub API request failed for %s", url)
        return None
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        logger.warning("GitHub API error %d for %s", r.status_code, url)
        return None
    try:
        return r.json()
    except ValueError:
        logger.warning("GitHub API returned non-JSON for %s", url)
        return None


# ---------------------------------------------------------------------------
# GitHubResolver
# ---------------------------------------------------------------------------


class GitHubResolver:
    """Detect GitHub repository renames/transfers and reconstruct URLs."""

    GITHUB_DOMAINS: set[str] = {"github.com", "raw.githubusercontent.com"}

    def __init__(self, token: str | None = None, *, client: Any | None = None) -> None:
        """Initialize with optional GitHub auth token and rate-limited client.

        Args:
            token: GitHub personal access token. If None, reads from
                   ``GITHUB_TOKEN`` environment variable. Note: when ``client``
                   is supplied, the client's own token is what's actually sent
                   on the wire; this kwarg is kept for backwards compatibility
                   with the previous urllib-based implementation.
            client: Optional ``GitHubRateLimitedClient`` for unified quota
                   accounting with another caller (e.g. the bulk-scan runner).
                   When None, a process-wide default client is used.
        """
        self._token = token or os.environ.get("GITHUB_TOKEN")
        self._client = client

    def is_github_url(self, url: str) -> bool:
        """Check if URL is a GitHub URL (exact domain match).

        Args:
            url: URL to check.

        Returns:
            True if the URL's hostname is in GITHUB_DOMAINS.
        """
        if not url:
            return False
        try:
            parsed = urlparse(url)
            return parsed.hostname in self.GITHUB_DOMAINS
        except Exception:
            return False

    def _parse_github_url(self, url: str) -> tuple[str, str, str | None]:
        """Parse GitHub URL into (owner, repo, file_path).

        Args:
            url: GitHub URL.

        Returns:
            Tuple of (owner, repo, file_path_or_None).
        """
        parsed = urlparse(url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]

        owner = parts[0] if len(parts) >= 1 else ""
        repo = parts[1] if len(parts) >= 2 else ""
        file_path = "/".join(parts[2:]) if len(parts) > 2 else None

        return owner, repo, file_path

    def resolve_repo_redirect(self, owner: str, repo: str) -> str | None:
        """Query GitHub API to detect repo rename/transfer.

        The GitHub API automatically follows 301 redirects for renamed repos
        and returns the current repository data.

        Args:
            owner: Repository owner (original).
            repo: Repository name (original).

        Returns:
            New repo HTML URL if renamed/transferred, None otherwise.
        """
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        try:
            data = _github_api_get(api_url, self._token, client=self._client)
        except Exception:
            logger.warning("GitHub API error resolving %s/%s", owner, repo)
            return None

        if data is None:
            return None

        full_name = data.get("full_name", "")
        current = f"{owner}/{repo}"

        if full_name.lower() != current.lower():
            new_url = data.get("html_url", f"https://github.com/{full_name}")
            logger.info("GitHub redirect detected: %s -> %s", current, full_name)
            return new_url

        return None

    def reconstruct_file_url(self, original_url: str, new_repo_url: str) -> str:
        """Reconstruct full file URL from original URL and new repo location.

        Replaces the owner/repo portion of the original URL with the new
        repo location, preserving the file path.

        Args:
            original_url: Original dead GitHub URL.
            new_repo_url: New repository URL from API.

        Returns:
            Reconstructed URL with new repo location.
        """
        orig_parsed = urlparse(original_url)
        new_parsed = urlparse(new_repo_url)

        orig_parts = [p for p in orig_parsed.path.strip("/").split("/") if p]
        new_parts = [p for p in new_parsed.path.strip("/").split("/") if p]

        # Get file path (everything after owner/repo)
        file_parts = orig_parts[2:] if len(orig_parts) > 2 else []

        # For raw.githubusercontent.com, reconstruct differently
        if orig_parsed.hostname == "raw.githubusercontent.com":
            new_owner = new_parts[0] if len(new_parts) >= 1 else ""
            new_repo = new_parts[1] if len(new_parts) >= 2 else ""
            path = "/".join(file_parts)
            if path:
                return f"https://raw.githubusercontent.com/{new_owner}/{new_repo}/{path}"
            return f"https://raw.githubusercontent.com/{new_owner}/{new_repo}"

        # Standard github.com URL
        new_base = new_repo_url.rstrip("/")
        if file_parts:
            return f"{new_base}/{'/'.join(file_parts)}"
        return new_base
