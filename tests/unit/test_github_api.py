"""Tests for GitHubContentsClient.

See LLD #67 §5: Unit tests using FakeGitHubContentsClient.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from gh_link_auditor.github_api import GitHubContentsClient
from tests.fakes.github_api import FakeGitHubContentsClient


def _make_transport(routes: dict[str, tuple[int, list | dict]]) -> httpx.MockTransport:
    """Create a MockTransport from a route mapping.

    Args:
        routes: Mapping of URL path -> (status_code, json_body).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in routes:
            status, body = routes[path]
            return httpx.Response(status, json=body)
        return httpx.Response(404, json={"message": "Not Found"})

    return httpx.MockTransport(handler)


class TestFakeGitHubContentsClient:
    """Tests for FakeGitHubContentsClient behavior."""

    def test_list_doc_files_filters_by_extension(self) -> None:
        client = FakeGitHubContentsClient()
        client.configure_repo_files("org", "repo", {
            "README.md": "# Hello",
            "docs/guide.rst": "Guide",
            "src/main.py": "print()",
            "notes.txt": "notes",
            "manual.adoc": "= Manual",
        })
        files = client.list_doc_files("org", "repo")
        assert files == ["README.md", "docs/guide.rst", "manual.adoc", "notes.txt"]

    def test_list_doc_files_returns_empty_for_unknown_repo(self) -> None:
        client = FakeGitHubContentsClient()
        files = client.list_doc_files("org", "repo")
        assert files == []

    def test_list_doc_files_returns_sorted(self) -> None:
        client = FakeGitHubContentsClient()
        client.configure_repo_files("org", "repo", {
            "z.md": "z",
            "a.md": "a",
            "m.md": "m",
        })
        files = client.list_doc_files("org", "repo")
        assert files == ["a.md", "m.md", "z.md"]

    def test_fetch_file_content_returns_content(self) -> None:
        client = FakeGitHubContentsClient()
        client.configure_repo_files("org", "repo", {
            "README.md": "# Hello World",
        })
        content = client.fetch_file_content("org", "repo", "README.md")
        assert content == "# Hello World"

    def test_fetch_file_content_raises_on_missing_file(self) -> None:
        client = FakeGitHubContentsClient()
        client.configure_repo_files("org", "repo", {})
        import pytest
        with pytest.raises(FileNotFoundError):
            client.fetch_file_content("org", "repo", "missing.md")

    def test_tracks_list_calls(self) -> None:
        client = FakeGitHubContentsClient()
        client.configure_repo_files("org", "repo", {"a.md": "a"})
        client.list_doc_files("org", "repo")
        assert client.list_doc_files_calls == [("org", "repo")]

    def test_tracks_fetch_calls(self) -> None:
        client = FakeGitHubContentsClient()
        client.configure_repo_files("org", "repo", {"a.md": "a"})
        client.fetch_file_content("org", "repo", "a.md")
        assert client.fetch_file_content_calls == [("org", "repo", "a.md")]

    def test_list_doc_files_case_insensitive_extension(self) -> None:
        client = FakeGitHubContentsClient()
        client.configure_repo_files("org", "repo", {
            "README.MD": "# Caps",
            "guide.Rst": "Guide",
        })
        files = client.list_doc_files("org", "repo")
        assert len(files) == 2


class TestGitHubContentsClient:
    """Tests for the real GitHubContentsClient using httpx MockTransport."""

    def _make_client(self, routes: dict[str, tuple[int, list | dict]]) -> GitHubContentsClient:
        """Create a GitHubContentsClient with a mocked transport."""
        transport = _make_transport(routes)
        client = GitHubContentsClient(token="fake-token")
        client._client = httpx.Client(
            base_url="https://api.github.com",
            transport=transport,
            headers=client._client.headers,
        )
        return client

    def test_list_doc_files_flat_repo(self) -> None:
        routes = {
            "/repos/org/repo/contents/": (200, [
                {"type": "file", "path": "README.md"},
                {"type": "file", "path": "main.py"},
                {"type": "file", "path": "CHANGELOG.txt"},
            ]),
        }
        client = self._make_client(routes)
        files = client.list_doc_files("org", "repo")
        assert files == ["CHANGELOG.txt", "README.md"]

    def test_list_doc_files_with_subdirectory(self) -> None:
        routes = {
            "/repos/org/repo/contents/": (200, [
                {"type": "file", "path": "README.md"},
                {"type": "dir", "path": "docs"},
            ]),
            "/repos/org/repo/contents/docs": (200, [
                {"type": "file", "path": "docs/guide.md"},
                {"type": "file", "path": "docs/api.rst"},
                {"type": "file", "path": "docs/config.yaml"},
            ]),
        }
        client = self._make_client(routes)
        files = client.list_doc_files("org", "repo")
        assert files == ["README.md", "docs/api.rst", "docs/guide.md"]

    def test_list_doc_files_empty_repo(self) -> None:
        routes = {
            "/repos/org/repo/contents/": (200, []),
        }
        client = self._make_client(routes)
        files = client.list_doc_files("org", "repo")
        assert files == []

    def test_list_doc_files_non_list_response(self) -> None:
        """Contents API returns a single file object for file paths."""
        routes = {
            "/repos/org/repo/contents/": (200, {"type": "file", "path": "README.md"}),
        }
        client = self._make_client(routes)
        files = client.list_doc_files("org", "repo")
        assert files == []

    def test_fetch_file_content_base64(self) -> None:
        content = "# Hello World\nThis is a test."
        encoded = base64.b64encode(content.encode()).decode()
        routes = {
            "/repos/org/repo/contents/README.md": (200, {
                "encoding": "base64",
                "content": encoded,
            }),
        }
        client = self._make_client(routes)
        result = client.fetch_file_content("org", "repo", "README.md")
        assert result == content

    def test_fetch_file_content_non_base64(self) -> None:
        routes = {
            "/repos/org/repo/contents/small.md": (200, {
                "encoding": "utf-8",
                "content": "# Small file",
            }),
        }
        client = self._make_client(routes)
        result = client.fetch_file_content("org", "repo", "small.md")
        assert result == "# Small file"

    def test_fetch_file_content_404_raises(self) -> None:
        routes: dict[str, tuple[int, list | dict]] = {}
        client = self._make_client(routes)
        with pytest.raises(FileNotFoundError, match="File not found"):
            client.fetch_file_content("org", "repo", "missing.md")

    def test_fetch_file_content_500_raises(self) -> None:
        routes = {
            "/repos/org/repo/contents/broken.md": (500, {"message": "Internal Server Error"}),
        }
        client = self._make_client(routes)
        with pytest.raises(httpx.HTTPStatusError):
            client.fetch_file_content("org", "repo", "broken.md")

    def test_close(self) -> None:
        client = GitHubContentsClient(token="fake")
        client.close()

    def test_auth_header_set(self) -> None:
        client = GitHubContentsClient(token="my-token")
        assert client._client.headers["authorization"] == "Bearer my-token"

    def test_no_auth_header_without_token(self) -> None:
        import os
        old = os.environ.pop("GITHUB_TOKEN", None)
        try:
            client = GitHubContentsClient(token="")
            assert "authorization" not in client._client.headers
        finally:
            if old is not None:
                os.environ["GITHUB_TOKEN"] = old

    def test_list_doc_files_api_error_raises(self) -> None:
        routes = {
            "/repos/org/repo/contents/": (500, {"message": "Server Error"}),
        }
        client = self._make_client(routes)
        with pytest.raises(httpx.HTTPStatusError):
            client.list_doc_files("org", "repo")
