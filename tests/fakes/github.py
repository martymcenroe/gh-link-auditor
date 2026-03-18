"""Fake GitHub API client for testing.

Replaces MagicMock with a configurable fake that mirrors GitHubClient's interface.
"""

from __future__ import annotations

from repo_scout.models import DiscoverySource, RepositoryRecord, make_repo_record


class FakeGitHubClient:
    """Fake GitHubClient with pre-configured responses.

    Configure data via configure_* methods, then call the same methods
    as the real GitHubClient.
    """

    def __init__(self) -> None:
        self._stargazers: dict[str, list[str]] = {}
        self._user_repos: dict[str, list[RepositoryRecord]] = {}
        self._starred: dict[str, list[RepositoryRecord]] = {}
        self._repos: dict[str, dict] = {}
        self._request_responses: dict[str, dict | list | None] = {}
        self.request_log: list[str] = []
        # Call tracking for assertion support
        self.get_stargazers_calls: list[tuple[str, str, int]] = []
        self.get_user_repos_calls: list[str] = []
        self.get_starred_calls: list[str] = []
        self.repo_exists_calls: list[str] = []
        self.close_calls: int = 0

    def configure_stargazers(self, owner_repo: str, users: list[str]) -> None:
        """Set stargazer usernames for a repo (e.g. "owner/repo")."""
        self._stargazers[owner_repo] = users

    def configure_user_repos(self, username: str, repos: list[RepositoryRecord]) -> None:
        """Set repos owned by a user."""
        self._user_repos[username] = repos

    def configure_starred(self, username: str, repos: list[RepositoryRecord]) -> None:
        """Set repos starred by a user."""
        self._starred[username] = repos

    def configure_repo(self, full_name: str, data: dict) -> None:
        """Set raw API response for a specific repo."""
        self._repos[full_name] = data

    def configure_request(self, endpoint: str, response: dict | list | None) -> None:
        """Set response for a raw request() call."""
        self._request_responses[endpoint] = response

    def get_stargazers(self, owner: str, repo: str, max_count: int = 100) -> list[str]:
        """Return configured stargazer usernames."""
        self.get_stargazers_calls.append((owner, repo, max_count))
        key = f"{owner}/{repo}"
        return self._stargazers.get(key, [])[:max_count]

    def get_user_repos(self, username: str) -> list[RepositoryRecord]:
        """Return configured user repos."""
        self.get_user_repos_calls.append(username)
        return self._user_repos.get(username, [])

    def get_starred(self, username: str) -> list[RepositoryRecord]:
        """Return configured starred repos."""
        self.get_starred_calls.append(username)
        return self._starred.get(username, [])

    def get_repo(self, owner: str, name: str) -> RepositoryRecord | None:
        """Return a RepositoryRecord if configured."""
        key = f"{owner}/{name}"
        data = self._repos.get(key)
        if data is None:
            return None
        return make_repo_record(
            owner=data.get("owner", {}).get("login", owner),
            name=data.get("name", name),
            source=DiscoverySource.STARRED_REPO,
            description=data.get("description"),
            stars=data.get("stargazers_count"),
        )

    def repo_exists(self, full_name: str) -> bool:
        """Check if a repo was configured."""
        self.repo_exists_calls.append(full_name)
        return full_name in self._repos

    def request(self, endpoint: str) -> dict | list | None:
        """Return configured response for an endpoint."""
        self.request_log.append(endpoint)
        return self._request_responses.get(endpoint)

    def close(self) -> None:
        """Track close call."""
        self.close_calls += 1
