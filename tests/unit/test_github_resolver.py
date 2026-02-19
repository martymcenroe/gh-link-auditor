"""Unit tests for GitHub URL resolver (LLD #20, §10.0).

TDD: Tests written BEFORE implementation.
Mock target: ``gh_link_auditor.github_resolver._github_api_get``
Covers: GitHubResolver.is_github_url(), resolve_repo_redirect(),
        reconstruct_file_url(), _parse_github_url()
"""

from unittest.mock import patch

from gh_link_auditor.github_resolver import GitHubResolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
        owner, repo, file_path = resolver._parse_github_url(
            "https://github.com/owner/repo/blob/main/README.md"
        )
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
