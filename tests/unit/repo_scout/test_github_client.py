"""Tests for repo_scout.github_client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from repo_scout.github_client import GitHubClient


class TestGitHubClientInit:
    """Tests for GitHubClient initialization."""

    def test_init_with_token(self) -> None:
        client = GitHubClient(token="ghp_test123")
        assert client.token == "ghp_test123"
        assert client.rate_limit_delay == 1.0
        client.close()

    def test_init_without_token(self) -> None:
        client = GitHubClient()
        assert client.token == ""
        client.close()

    def test_init_custom_delay(self) -> None:
        client = GitHubClient(rate_limit_delay=0.5)
        assert client.rate_limit_delay == 0.5
        client.close()

    def test_auth_header_set_when_token_provided(self) -> None:
        client = GitHubClient(token="ghp_abc")
        headers = client._client.headers
        assert headers["authorization"] == "Bearer ghp_abc"
        client.close()

    def test_no_auth_header_without_token(self) -> None:
        client = GitHubClient(token="")
        headers = client._client.headers
        assert "authorization" not in headers
        client.close()


class TestRateLimit:
    """Tests for rate limiting."""

    @patch("repo_scout.github_client.time")
    def test_rate_limit_enforced(self, mock_time: MagicMock) -> None:
        mock_time.time.side_effect = [0.0, 0.5, 1.5]
        client = GitHubClient(rate_limit_delay=1.0)
        client._last_request_time = 0.0

        # Elapsed is 0.5, need 0.5 more
        mock_time.time.side_effect = [0.5, 1.5]
        client._wait_for_rate_limit()
        mock_time.sleep.assert_called_once_with(0.5)
        client.close()

    @patch("repo_scout.github_client.time")
    def test_no_wait_if_enough_time_passed(self, mock_time: MagicMock) -> None:
        client = GitHubClient(rate_limit_delay=1.0)
        client._last_request_time = 0.0

        # Elapsed is 2.0, no wait needed
        mock_time.time.side_effect = [2.0, 2.0]
        client._wait_for_rate_limit()
        mock_time.sleep.assert_not_called()
        client.close()


class TestRequest:
    """Tests for request method."""

    def test_success_200(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 1}

        with patch.object(client._client, "get", return_value=mock_response):
            result = client.request("/repos/owner/name")
        assert result == {"id": 1}
        client.close()

    def test_not_found_404(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(client._client, "get", return_value=mock_response):
            result = client.request("/repos/owner/nonexistent")
        assert result is None
        client.close()

    def test_other_status_code(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch.object(client._client, "get", return_value=mock_response):
            result = client.request("/repos/owner/name")
        assert result is None
        client.close()

    def test_http_error(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)

        with patch.object(client._client, "get", side_effect=httpx.ConnectError("fail")):
            result = client.request("/repos/owner/name")
        assert result is None
        client.close()

    def test_full_url_used_when_no_slash_prefix(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}

        with patch.object(client._client, "get", return_value=mock_response) as mock_get:
            client.request("https://custom.api/endpoint")
        mock_get.assert_called_once_with("https://custom.api/endpoint")
        client.close()


class TestGetRepo:
    """Tests for get_repo method."""

    def test_success(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        api_response = {
            "owner": {"login": "octocat"},
            "name": "hello-world",
            "description": "My first repo",
            "stargazers_count": 1000,
        }
        with patch.object(client, "request", return_value=api_response):
            record = client.get_repo("octocat", "hello-world")

        assert record is not None
        assert record["owner"] == "octocat"
        assert record["name"] == "hello-world"
        assert record["description"] == "My first repo"
        assert record["stars"] == 1000
        client.close()

    def test_not_found(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        with patch.object(client, "request", return_value=None):
            record = client.get_repo("octocat", "nonexistent")
        assert record is None
        client.close()

    def test_non_dict_response(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        with patch.object(client, "request", return_value=[]):
            record = client.get_repo("octocat", "hello")
        assert record is None
        client.close()


class TestGetStarred:
    """Tests for get_starred method."""

    def test_single_page(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        api_response = [
            {
                "owner": {"login": "octocat"},
                "name": "hello",
                "description": "Test",
                "stargazers_count": 10,
            },
        ]
        with patch.object(client, "request", return_value=api_response):
            records = client.get_starred("user1")

        assert len(records) == 1
        assert records[0]["owner"] == "octocat"
        client.close()

    def test_empty(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        with patch.object(client, "request", return_value=[]):
            records = client.get_starred("user1")
        assert records == []
        client.close()

    def test_none_response(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        with patch.object(client, "request", return_value=None):
            records = client.get_starred("user1")
        assert records == []
        client.close()

    def test_multi_page(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        # First page: 100 repos (full page), second page: 1 repo (last page)
        page1 = [
            {"owner": {"login": f"o{i}"}, "name": f"r{i}", "description": None, "stargazers_count": 0}
            for i in range(100)
        ]
        page2 = [{"owner": {"login": "final"}, "name": "repo", "description": None, "stargazers_count": 0}]

        with patch.object(client, "request", side_effect=[page1, page2]):
            records = client.get_starred("user1")

        assert len(records) == 101
        client.close()

    def test_non_list_response_stops(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        with patch.object(client, "request", return_value={"error": True}):
            records = client.get_starred("user1")
        assert records == []
        client.close()


class TestGetStargazers:
    """Tests for get_stargazers method."""

    def test_single_page(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        api_response = [
            {"login": "alice", "id": 1},
            {"login": "bob", "id": 2},
        ]
        with patch.object(client, "request", return_value=api_response):
            result = client.get_stargazers("org", "repo")
        assert result == ["alice", "bob"]
        client.close()

    def test_empty(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        with patch.object(client, "request", return_value=[]):
            result = client.get_stargazers("org", "repo")
        assert result == []
        client.close()

    def test_multi_page(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        page1 = [{"login": f"u{i}", "id": i} for i in range(100)]
        page2 = [{"login": "last", "id": 999}]
        with patch.object(client, "request", side_effect=[page1, page2]):
            result = client.get_stargazers("org", "repo", max_count=200)
        assert len(result) == 101
        client.close()

    def test_max_count_caps_results(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        page1 = [{"login": f"u{i}", "id": i} for i in range(100)]
        page2 = [{"login": f"v{i}", "id": 100 + i} for i in range(100)]
        with patch.object(client, "request", side_effect=[page1, page2]):
            result = client.get_stargazers("org", "repo", max_count=150)
        assert len(result) == 150
        client.close()

    def test_non_list_response_returns_empty(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        with patch.object(client, "request", return_value={"error": True}):
            result = client.get_stargazers("org", "repo")
        assert result == []
        client.close()

    def test_none_response_returns_empty(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        with patch.object(client, "request", return_value=None):
            result = client.get_stargazers("org", "repo")
        assert result == []
        client.close()


class TestGetUserRepos:
    """Tests for get_user_repos method."""

    def test_basic(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        api_response = [
            {
                "owner": {"login": "alice"},
                "name": "my-tool",
                "description": "A tool",
                "stargazers_count": 42,
                "pushed_at": "2026-02-01T00:00:00Z",
                "has_issues": True,
                "language": "Python",
                "fork": False,
                "archived": False,
            },
        ]
        with patch.object(client, "request", return_value=api_response):
            records = client.get_user_repos("alice")
        assert len(records) == 1
        assert records[0]["owner"] == "alice"
        assert records[0]["name"] == "my-tool"
        assert records[0]["sources"] == ["stargazer_target"]
        client.close()

    def test_filters_forks(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        api_response = [
            {
                "owner": {"login": "alice"},
                "name": "forked-repo",
                "description": None,
                "stargazers_count": 0,
                "pushed_at": "2026-01-01T00:00:00Z",
                "has_issues": True,
                "language": None,
                "fork": True,
                "archived": False,
            },
        ]
        with patch.object(client, "request", return_value=api_response):
            records = client.get_user_repos("alice")
        assert records == []
        client.close()

    def test_filters_archived(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        api_response = [
            {
                "owner": {"login": "alice"},
                "name": "old-repo",
                "description": None,
                "stargazers_count": 0,
                "pushed_at": "2026-01-01T00:00:00Z",
                "has_issues": True,
                "language": None,
                "fork": False,
                "archived": True,
            },
        ]
        with patch.object(client, "request", return_value=api_response):
            records = client.get_user_repos("alice")
        assert records == []
        client.close()

    def test_empty(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        with patch.object(client, "request", return_value=[]):
            records = client.get_user_repos("alice")
        assert records == []
        client.close()

    def test_metadata_fields(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        api_response = [
            {
                "owner": {"login": "alice"},
                "name": "tool",
                "description": "desc",
                "stargazers_count": 5,
                "pushed_at": "2026-02-15T10:00:00Z",
                "has_issues": False,
                "language": "TypeScript",
                "fork": False,
                "archived": False,
            },
        ]
        with patch.object(client, "request", return_value=api_response):
            records = client.get_user_repos("alice")
        meta = records[0]["metadata"]
        assert meta["pushed_at"] == "2026-02-15T10:00:00Z"
        assert meta["has_issues"] is False
        assert meta["language"] == "TypeScript"
        client.close()

    def test_none_response_returns_empty(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        with patch.object(client, "request", return_value=None):
            records = client.get_user_repos("alice")
        assert records == []
        client.close()

    def test_non_list_response_returns_empty(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        with patch.object(client, "request", return_value={"error": True}):
            records = client.get_user_repos("alice")
        assert records == []
        client.close()


class TestRepoExists:
    """Tests for repo_exists method."""

    def test_exists(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        with patch.object(client, "request", return_value={"id": 1}):
            assert client.repo_exists("owner/repo") is True
        client.close()

    def test_not_exists(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        with patch.object(client, "request", return_value=None):
            assert client.repo_exists("owner/nonexistent") is False
        client.close()

    def test_invalid_format(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        assert client.repo_exists("invalid-no-slash") is False
        client.close()

    def test_too_many_slashes(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        assert client.repo_exists("a/b/c") is False
        client.close()


class TestClose:
    """Tests for close method."""

    def test_close(self) -> None:
        client = GitHubClient(rate_limit_delay=0.0)
        with patch.object(client._client, "close") as mock_close:
            client.close()
        mock_close.assert_called_once()
