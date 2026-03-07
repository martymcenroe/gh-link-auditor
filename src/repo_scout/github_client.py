"""GitHub API client with rate limiting.

See LLD #3 §2.4 for GitHubClient specification.
Deviation: synchronous (not async) to match codebase conventions.
"""

from __future__ import annotations

import logging
import time

import httpx

from repo_scout.models import DiscoverySource, RepositoryRecord, make_repo_record

logger = logging.getLogger(__name__)

_API_BASE = "https://api.github.com"


class GitHubClient:
    """GitHub API wrapper with rate limiting."""

    def __init__(self, token: str = "", rate_limit_delay: float = 1.0) -> None:
        """Initialize with auth token and rate limiting.

        Args:
            token: GitHub personal access token.
            rate_limit_delay: Seconds between API calls.
        """
        self.token = token
        self.rate_limit_delay = rate_limit_delay
        self._last_request_time: float = 0.0
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(headers=headers, timeout=30.0)

    def _wait_for_rate_limit(self) -> None:
        """Enforce minimum delay between API calls."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    def request(self, endpoint: str) -> dict | list | None:
        """Make API request respecting rate limits.

        Args:
            endpoint: API endpoint path (e.g. /repos/org/repo).

        Returns:
            Parsed JSON response, or None on error.
        """
        self._wait_for_rate_limit()
        url = f"{_API_BASE}{endpoint}" if endpoint.startswith("/") else endpoint
        try:
            response = self._client.get(url)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 404:
                return None
            logger.warning("GitHub API %s returned %d", endpoint, response.status_code)
            return None
        except httpx.HTTPError:
            logger.exception("GitHub API request failed: %s", endpoint)
            return None

    def get_repo(self, owner: str, name: str) -> RepositoryRecord | None:
        """Fetch repository details.

        Args:
            owner: Repository owner.
            name: Repository name.

        Returns:
            RepositoryRecord or None if not found.
        """
        data = self.request(f"/repos/{owner}/{name}")
        if not data or not isinstance(data, dict):
            return None

        return make_repo_record(
            owner=data.get("owner", {}).get("login", owner),
            name=data.get("name", name),
            source=DiscoverySource.STARRED_REPO,
            description=data.get("description"),
            stars=data.get("stargazers_count"),
        )

    def get_starred(self, username: str) -> list[RepositoryRecord]:
        """Fetch user's starred repositories.

        Args:
            username: GitHub username.

        Returns:
            List of RepositoryRecords.
        """
        records: list[RepositoryRecord] = []
        page = 1
        while True:
            data = self.request(f"/users/{username}/starred?per_page=100&page={page}")
            if not data or not isinstance(data, list) or len(data) == 0:
                break
            for repo in data:
                records.append(
                    make_repo_record(
                        owner=repo.get("owner", {}).get("login", ""),
                        name=repo.get("name", ""),
                        source=DiscoverySource.STARRED_REPO,
                        description=repo.get("description"),
                        stars=repo.get("stargazers_count"),
                    )
                )
            if len(data) < 100:
                break
            page += 1
        return records

    def get_stargazers(self, owner: str, repo: str, max_count: int = 100) -> list[str]:
        """Fetch usernames who starred a repository.

        Args:
            owner: Repository owner.
            repo: Repository name.
            max_count: Maximum stargazers to return.

        Returns:
            List of GitHub usernames.
        """
        usernames: list[str] = []
        page = 1
        while len(usernames) < max_count:
            data = self.request(f"/repos/{owner}/{repo}/stargazers?per_page=100&page={page}")
            if not data or not isinstance(data, list) or len(data) == 0:
                break
            for user in data:
                if len(usernames) >= max_count:
                    break
                usernames.append(user.get("login", ""))
            if len(data) < 100:
                break
            page += 1
        return usernames

    def get_user_repos(self, username: str) -> list[RepositoryRecord]:
        """Fetch repositories owned by a user, excluding forks and archives.

        Args:
            username: GitHub username.

        Returns:
            List of RepositoryRecords with STARGAZER_TARGET source.
        """
        data = self.request(f"/users/{username}/repos?type=owner&sort=updated&per_page=100")
        if not data or not isinstance(data, list):
            return []

        records: list[RepositoryRecord] = []
        for repo in data:
            if repo.get("fork", False) or repo.get("archived", False):
                continue
            records.append(
                make_repo_record(
                    owner=repo.get("owner", {}).get("login", username),
                    name=repo.get("name", ""),
                    source=DiscoverySource.STARGAZER_TARGET,
                    description=repo.get("description"),
                    stars=repo.get("stargazers_count"),
                    metadata={
                        "pushed_at": repo.get("pushed_at"),
                        "has_issues": repo.get("has_issues", False),
                        "language": repo.get("language"),
                    },
                )
            )
        return records

    def repo_exists(self, full_name: str) -> bool:
        """Check if a repository exists.

        Args:
            full_name: "owner/name" format.

        Returns:
            True if repository exists.
        """
        parts = full_name.split("/")
        if len(parts) != 2:
            return False
        data = self.request(f"/repos/{parts[0]}/{parts[1]}")
        return data is not None

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()
