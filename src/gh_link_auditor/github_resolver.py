"""GitHub API resolver for detecting repo renames and transfers.

Queries the GitHub REST API to detect 301 redirects for renamed or
transferred repositories, and reconstructs file URLs under the new location.

See LLD #20 §2.4 for API specification.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

from src.logging_config import setup_logging

logger = setup_logging("github_resolver")


# ---------------------------------------------------------------------------
# Internal API helper (mock target for testing)
# ---------------------------------------------------------------------------


def _github_api_get(url: str, token: str | None = None) -> dict | None:
    """Make a GET request to the GitHub API.

    Args:
        url: GitHub API endpoint URL.
        token: Optional GitHub personal access token.

    Returns:
        Parsed JSON response dict, or None on error/404.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "gh-link-auditor/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        logger.warning("GitHub API error %d for %s", e.code, url)
        return None
    except (urllib.error.URLError, OSError) as e:
        logger.warning("GitHub API request failed for %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# GitHubResolver
# ---------------------------------------------------------------------------


class GitHubResolver:
    """Detect GitHub repository renames/transfers and reconstruct URLs."""

    GITHUB_DOMAINS: set[str] = {"github.com", "raw.githubusercontent.com"}

    def __init__(self, token: str | None = None) -> None:
        """Initialize with optional GitHub auth token.

        Args:
            token: GitHub personal access token. If None, reads from
                   ``GITHUB_TOKEN`` environment variable.
        """
        self._token = token or os.environ.get("GITHUB_TOKEN")

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
            data = _github_api_get(api_url, self._token)
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
