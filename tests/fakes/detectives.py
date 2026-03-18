"""Fake detective components for testing.

Replaces MagicMock with configurable fakes for RedirectResolver,
GitHubResolver, and URLHeuristic.
"""

from __future__ import annotations


class FakeRedirectResolver:
    """Fake RedirectResolver with configurable redirect behavior."""

    def __init__(
        self,
        redirect_map: dict[str, tuple[str | None, list[str]]] | None = None,
        mutations: dict[str, list[tuple[str, str]]] | None = None,
        live_urls: set[str] | None = None,
    ) -> None:
        self._redirect_map = redirect_map or {}
        self._mutations = mutations or {}
        self._live_urls = live_urls or set()

    def follow_redirects(self, url: str) -> tuple[str | None, list[str]]:
        """Return configured redirect result for url."""
        return self._redirect_map.get(url, (None, ["No redirect chain detected"]))

    def test_url_mutations(self, url: str) -> list[tuple[str, str]]:
        """Return configured mutation results for url."""
        return self._mutations.get(url, [])

    def verify_live(self, url: str) -> bool:
        """Return True if url is in the live_urls set."""
        return url in self._live_urls


class FakeGitHubResolver:
    """Fake GitHubResolver with configurable redirect detection."""

    GITHUB_DOMAINS: set[str] = {"github.com", "raw.githubusercontent.com"}

    def __init__(
        self,
        redirects: dict[str, str] | None = None,
        github_urls: set[str] | None = None,
    ) -> None:
        self._redirects = redirects or {}
        self._github_urls = github_urls or set()

    def is_github_url(self, url: str) -> bool:
        """Return True if url was configured as a GitHub URL."""
        if self._github_urls:
            return url in self._github_urls
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return parsed.hostname in self.GITHUB_DOMAINS

    def _parse_github_url(self, url: str) -> tuple[str, str, str | None]:
        """Parse GitHub URL into (owner, repo, file_path)."""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        owner = parts[0] if len(parts) >= 1 else ""
        repo = parts[1] if len(parts) >= 2 else ""
        file_path = "/".join(parts[2:]) if len(parts) > 2 else None
        return owner, repo, file_path

    def resolve_repo_redirect(self, owner: str, repo: str) -> str | None:
        """Return configured redirect for owner/repo."""
        key = f"{owner}/{repo}"
        return self._redirects.get(key)

    def reconstruct_file_url(self, original_url: str, new_repo_url: str) -> str:
        """Reconstruct file URL from original and new repo URL."""
        from urllib.parse import urlparse

        orig_parsed = urlparse(original_url)
        orig_parts = [p for p in orig_parsed.path.strip("/").split("/") if p]
        file_parts = orig_parts[2:] if len(orig_parts) > 2 else []
        new_base = new_repo_url.rstrip("/")
        if file_parts:
            return f"{new_base}/{'/'.join(file_parts)}"
        return new_base


class FakeURLHeuristic:
    """Fake URLHeuristic with configurable candidate generation."""

    def __init__(
        self,
        candidates: list[str] | None = None,
        live: list[str] | None = None,
    ) -> None:
        self._candidates = candidates or []
        self._live = live or []

    def generate_candidates(self, domain: str, title: str, path: str) -> list[str]:
        """Return pre-configured candidates."""
        return self._candidates

    def probe_candidates(self, candidates: list[str], max_results: int = 3) -> list[str]:
        """Return pre-configured live URLs."""
        return self._live[:max_results]
