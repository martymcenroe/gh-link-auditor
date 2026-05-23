"""Unit tests for GitHub URL resolver (LLD #20, §10.0; LLD-257).

TDD: Tests written BEFORE implementation.
Mock target: ``gh_link_auditor.github_resolver._github_api_get`` for the
high-level tests; an injected client for the lower-level tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import httpx

from gh_link_auditor.github_resolver import (
    GitHubResolver,
    _get_default_client,
    _github_api_get,
)

# ---------------------------------------------------------------------------
# Inline test doubles (no MagicMock — keeps the suite consistent with the
# tests/fakes/ pattern: typed, predictable, easy to read at the call site)
# ---------------------------------------------------------------------------


class _FakeHttpxResponse:
    """Minimal httpx.Response stand-in for github_resolver consumption."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        text: str = "",
        json_data: Any = None,
        raise_json: bool = False,
    ) -> None:
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})
        self.text = text
        self._json_data = json_data
        self._raise_json = raise_json

    def json(self) -> Any:
        if self._raise_json:
            raise ValueError("not JSON")
        return self._json_data


class _FakeRateLimitedClient:
    """Drop-in for GitHubRateLimitedClient that records calls."""

    def __init__(
        self,
        *,
        response: _FakeHttpxResponse | None = None,
        responses: list[_FakeHttpxResponse] | None = None,
        side_effect: Exception | None = None,
    ) -> None:
        self._response = response
        self._responses = list(responses or [])
        self._side_effect = side_effect
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> _FakeHttpxResponse:
        self.calls.append(url)
        if self._side_effect is not None:
            raise self._side_effect
        if self._responses:
            return self._responses.pop(0)
        assert self._response is not None, "fake client has no response configured"
        return self._response


def _make_resolver() -> GitHubResolver:
    return GitHubResolver()


# ---------------------------------------------------------------------------
# is_github_url
# ---------------------------------------------------------------------------


class TestIsGitHubUrl:
    def test_github_com(self):
        resolver = _make_resolver()
        assert resolver.is_github_url("https://github.com/owner/repo") is True

    def test_raw_githubusercontent(self):
        resolver = _make_resolver()
        assert resolver.is_github_url("https://raw.githubusercontent.com/owner/repo/main/file.md") is True

    def test_not_github(self):
        resolver = _make_resolver()
        assert resolver.is_github_url("https://gitlab.com/owner/repo") is False

    def test_empty_url(self):
        resolver = _make_resolver()
        assert resolver.is_github_url("") is False

    def test_github_subdomain(self):
        """Only exact domain matches, not subdomains like docs.github.com."""
        resolver = _make_resolver()
        assert resolver.is_github_url("https://docs.github.com/en/actions") is False


# ---------------------------------------------------------------------------
# _parse_github_url
# ---------------------------------------------------------------------------


class TestParseGitHubUrl:
    def test_repo_root(self):
        resolver = _make_resolver()
        owner, repo, file_path = resolver._parse_github_url("https://github.com/owner/repo")
        assert owner == "owner"
        assert repo == "repo"
        assert file_path is None

    def test_repo_with_file(self):
        resolver = _make_resolver()
        owner, repo, file_path = resolver._parse_github_url("https://github.com/owner/repo/blob/main/README.md")
        assert owner == "owner"
        assert repo == "repo"
        assert file_path == "blob/main/README.md"

    def test_raw_githubusercontent(self):
        resolver = _make_resolver()
        owner, repo, file_path = resolver._parse_github_url(
            "https://raw.githubusercontent.com/owner/repo/main/docs/file.md"
        )
        assert owner == "owner"
        assert repo == "repo"
        assert file_path == "main/docs/file.md"

    def test_repo_with_trailing_slash(self):
        resolver = _make_resolver()
        owner, repo, file_path = resolver._parse_github_url("https://github.com/owner/repo/")
        assert owner == "owner"
        assert repo == "repo"


# ---------------------------------------------------------------------------
# T060: GitHub rename detection (REQ-4)
# ---------------------------------------------------------------------------


class TestResolveRepoRedirect:
    def test_rename_detected(self):
        """GitHub API returns new repo URL for renamed repo."""
        resolver = _make_resolver()
        api_response = {
            "full_name": "new-owner/new-repo",
            "html_url": "https://github.com/new-owner/new-repo",
        }
        with patch("gh_link_auditor.github_resolver._github_api_get", return_value=api_response):
            new_url = resolver.resolve_repo_redirect("old-owner", "old-repo")
        assert new_url == "https://github.com/new-owner/new-repo"

    def test_no_rename(self):
        """Same owner/repo returned — no rename happened."""
        resolver = _make_resolver()
        api_response = {
            "full_name": "owner/repo",
            "html_url": "https://github.com/owner/repo",
        }
        with patch("gh_link_auditor.github_resolver._github_api_get", return_value=api_response):
            new_url = resolver.resolve_repo_redirect("owner", "repo")
        assert new_url is None  # No redirect needed

    def test_repo_not_found(self):
        """404 from API — repo deleted."""
        resolver = _make_resolver()
        with patch("gh_link_auditor.github_resolver._github_api_get", return_value=None):
            new_url = resolver.resolve_repo_redirect("owner", "deleted-repo")
        assert new_url is None

    def test_api_error_returns_none(self):
        """Exception from API returns None gracefully."""
        resolver = _make_resolver()
        with patch(
            "gh_link_auditor.github_resolver._github_api_get",
            side_effect=Exception("rate limited"),
        ):
            new_url = resolver.resolve_repo_redirect("owner", "repo")
        assert new_url is None


# ---------------------------------------------------------------------------
# reconstruct_file_url
# ---------------------------------------------------------------------------


class TestReconstructFileUrl:
    def test_basic_reconstruction(self):
        """Reconstruct file URL from original + new repo."""
        resolver = _make_resolver()
        original = "https://github.com/old-owner/old-repo/blob/main/docs/guide.md"
        new_repo = "https://github.com/new-owner/new-repo"
        result = resolver.reconstruct_file_url(original, new_repo)
        assert result == "https://github.com/new-owner/new-repo/blob/main/docs/guide.md"

    def test_repo_root_reconstruction(self):
        """Repo root URL returns just the new repo URL."""
        resolver = _make_resolver()
        original = "https://github.com/old-owner/old-repo"
        new_repo = "https://github.com/new-owner/new-repo"
        result = resolver.reconstruct_file_url(original, new_repo)
        assert result == "https://github.com/new-owner/new-repo"

    def test_raw_content_reconstruction(self):
        """Reconstruct raw.githubusercontent.com URL."""
        resolver = _make_resolver()
        original = "https://raw.githubusercontent.com/old-owner/old-repo/main/file.txt"
        new_repo = "https://github.com/new-owner/new-repo"
        result = resolver.reconstruct_file_url(original, new_repo)
        assert "new-owner" in result
        assert "new-repo" in result
        assert "file.txt" in result


# ---------------------------------------------------------------------------
# Internal _github_api_get coverage (LLD-257: rewritten to mock the client
# rather than urllib.request.urlopen)
# ---------------------------------------------------------------------------


class TestGitHubApiGet:
    def test_api_get_success(self):
        """_github_api_get returns parsed JSON on success via injected client."""
        fake = _FakeRateLimitedClient(
            response=_FakeHttpxResponse(status_code=200, json_data={"full_name": "owner/repo"}),
        )
        result = _github_api_get("https://api.github.com/repos/owner/repo", client=fake)
        assert result == {"full_name": "owner/repo"}
        assert fake.calls == ["https://api.github.com/repos/owner/repo"]

    def test_api_get_404(self):
        """_github_api_get returns None silently on 404."""
        fake = _FakeRateLimitedClient(response=_FakeHttpxResponse(status_code=404))
        result = _github_api_get("https://api.github.com/repos/owner/gone", client=fake)
        assert result is None

    def test_api_get_non_404_error(self):
        """_github_api_get returns None on non-404 HTTP error (e.g. 500)."""
        fake = _FakeRateLimitedClient(response=_FakeHttpxResponse(status_code=500))
        result = _github_api_get("https://api.github.com/repos/owner/repo", client=fake)
        assert result is None

    def test_api_get_transport_error(self):
        """_github_api_get returns None when the client raises httpx.HTTPError."""
        fake = _FakeRateLimitedClient(side_effect=httpx.ConnectError("dns"))
        result = _github_api_get("https://api.github.com/repos/owner/repo", client=fake)
        assert result is None

    def test_api_get_non_json_body(self):
        """_github_api_get returns None when the response body is not JSON."""
        fake = _FakeRateLimitedClient(
            response=_FakeHttpxResponse(status_code=200, raise_json=True),
        )
        result = _github_api_get("https://api.github.com/repos/owner/repo", client=fake)
        assert result is None


# ---------------------------------------------------------------------------
# Token from env
# ---------------------------------------------------------------------------


class TestTokenFromEnv:
    def test_reads_token_from_env(self):
        """GitHubResolver reads GITHUB_TOKEN from environment."""
        with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_envtoken"}):
            resolver = GitHubResolver()
        assert resolver._token == "ghp_envtoken"

    def test_explicit_token_overrides_env(self):
        """Explicit token takes precedence over env."""
        with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_envtoken"}):
            resolver = GitHubResolver(token="ghp_explicit")
        assert resolver._token == "ghp_explicit"


# ---------------------------------------------------------------------------
# LLD-257: Client injection
# ---------------------------------------------------------------------------


class TestClientInjection:
    def test_resolver_uses_injected_client(self):
        """When client= is passed to GitHubResolver, it's used end-to-end."""
        fake = _FakeRateLimitedClient(
            response=_FakeHttpxResponse(
                status_code=200,
                json_data={
                    "full_name": "new-owner/new-repo",
                    "html_url": "https://github.com/new-owner/new-repo",
                },
            ),
        )
        resolver = GitHubResolver(client=fake)
        new_url = resolver.resolve_repo_redirect("old-owner", "old-repo")
        assert new_url == "https://github.com/new-owner/new-repo"
        assert fake.calls == ["https://api.github.com/repos/old-owner/old-repo"]

    def test_resolver_default_client_used_when_no_injection(self):
        """No client= → resolver routes through _get_default_client."""
        fake = _FakeRateLimitedClient(
            response=_FakeHttpxResponse(
                status_code=200,
                json_data={
                    "full_name": "owner/repo",
                    "html_url": "https://github.com/owner/repo",
                },
            ),
        )
        with patch("gh_link_auditor.github_resolver._get_default_client", return_value=fake):
            resolver = GitHubResolver()  # no client kwarg
            resolver.resolve_repo_redirect("owner", "repo")
        assert fake.calls == ["https://api.github.com/repos/owner/repo"]


# ---------------------------------------------------------------------------
# LLD-257: Module-level singleton default client
# ---------------------------------------------------------------------------


class TestDefaultClientFactory:
    def test_default_client_is_singleton(self, monkeypatch):
        """Two _get_default_client() calls return the same instance."""
        import gh_link_auditor.github_resolver as gr

        # Reset cached singleton so the test controls construction
        monkeypatch.setattr(gr, "_default_client", None)

        construction_calls = []

        class _StubClient:
            def __init__(self, *args, **kwargs):
                construction_calls.append(kwargs)

        monkeypatch.setattr(
            "gh_link_auditor.bulk_scan.gh_client.GitHubRateLimitedClient",
            _StubClient,
        )
        monkeypatch.setattr(
            "gh_link_auditor.auth.resolve_github_token",
            lambda: "test-token",
        )

        c1 = _get_default_client()
        c2 = _get_default_client()

        assert c1 is c2
        assert len(construction_calls) == 1
        assert construction_calls[0].get("token") == "test-token"

    def test_default_client_empty_token_passes_none(self, monkeypatch):
        """resolve_github_token() returning empty string passes None as token."""
        import gh_link_auditor.github_resolver as gr

        monkeypatch.setattr(gr, "_default_client", None)

        seen_kwargs = {}

        class _StubClient:
            def __init__(self, *args, **kwargs):
                seen_kwargs.update(kwargs)

        monkeypatch.setattr(
            "gh_link_auditor.bulk_scan.gh_client.GitHubRateLimitedClient",
            _StubClient,
        )
        monkeypatch.setattr(
            "gh_link_auditor.auth.resolve_github_token",
            lambda: "",
        )

        _get_default_client()
        assert seen_kwargs.get("token") is None


# ---------------------------------------------------------------------------
# LLD-257: Rate-limit behavior through the real GitHubRateLimitedClient
# (integration layer — exercises the wired-up client end-to-end)
# ---------------------------------------------------------------------------


def _import_real_client():
    """Lazy import to keep test collection cheap."""
    from gh_link_auditor.bulk_scan.gh_client import GitHubRateLimitedClient

    return GitHubRateLimitedClient


class TestRateLimitBehavior:
    def test_403_with_remaining_zero_triggers_backoff_then_succeeds(self, monkeypatch):
        """403 + X-RateLimit-Remaining: 0 is treated as a rate-limit; retry succeeds."""
        Client = _import_real_client()
        client = Client(
            token="t",
            per_request_delay_s=0.0,
            max_retries=3,
            max_backoff_s=1.0,
            base_backoff_s=0.01,
        )

        responses = [
            _FakeHttpxResponse(
                status_code=403,
                headers={"X-RateLimit-Remaining": "0"},
                text="API rate limit exceeded",
            ),
            _FakeHttpxResponse(
                status_code=200,
                json_data={
                    "full_name": "new/repo",
                    "html_url": "https://github.com/new/repo",
                },
            ),
        ]

        sleeps: list[float] = []
        monkeypatch.setattr("gh_link_auditor.bulk_scan.gh_client.time.sleep", lambda s: sleeps.append(s))
        monkeypatch.setattr(client._client, "request", lambda *a, **kw: responses.pop(0))

        resolver = GitHubResolver(client=client)
        result = resolver.resolve_repo_redirect("old", "repo")

        assert result == "https://github.com/new/repo"
        assert client.total_secondary_limits == 1
        assert any(s > 0 for s in sleeps), f"expected backoff sleep, got {sleeps}"
        client.close()

    def test_x_ratelimit_reset_wait_honored(self, monkeypatch):
        """When _remaining is at watermark, wait until _reset_at."""
        Client = _import_real_client()
        client = Client(
            token="t",
            per_request_delay_s=0.0,
            low_watermark=100,
        )
        client._remaining = 50  # below watermark
        client._reset_at = datetime.now(timezone.utc) + timedelta(seconds=3)

        responses = [
            _FakeHttpxResponse(
                status_code=200,
                json_data={"full_name": "old/repo", "html_url": "https://github.com/old/repo"},
            ),
        ]
        sleeps: list[float] = []
        monkeypatch.setattr("gh_link_auditor.bulk_scan.gh_client.time.sleep", lambda s: sleeps.append(s))
        monkeypatch.setattr(client._client, "request", lambda *a, **kw: responses.pop(0))

        resolver = GitHubResolver(client=client)
        resolver.resolve_repo_redirect("old", "repo")

        # The watermark wait should fire honoring the reset epoch. gh_client
        # adds a 1s safety buffer past _reset_at, so a 3s-out reset → ~4s sleep.
        assert any(s >= 3.0 for s in sleeps), f"expected reset wait >=3s, got {sleeps}"
        client.close()

    def test_retry_after_header_honored(self, monkeypatch):
        """429 with Retry-After: 1 sleeps ~1s before retrying."""
        Client = _import_real_client()
        client = Client(
            token="t",
            per_request_delay_s=0.0,
            max_retries=3,
            max_backoff_s=10.0,
            base_backoff_s=0.01,
        )

        responses = [
            _FakeHttpxResponse(status_code=429, headers={"Retry-After": "1"}, text=""),
            _FakeHttpxResponse(
                status_code=200,
                json_data={"full_name": "old/repo", "html_url": "https://github.com/old/repo"},
            ),
        ]
        sleeps: list[float] = []
        monkeypatch.setattr("gh_link_auditor.bulk_scan.gh_client.time.sleep", lambda s: sleeps.append(s))
        monkeypatch.setattr(client._client, "request", lambda *a, **kw: responses.pop(0))

        resolver = GitHubResolver(client=client)
        resolver.resolve_repo_redirect("old", "repo")

        assert 1.0 in sleeps, f"expected exactly 1.0 in sleeps, got {sleeps}"
        assert client.total_429s == 1
        client.close()
