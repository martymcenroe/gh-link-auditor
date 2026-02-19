"""Tests for repo_scout.awesome_parser."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from repo_scout.awesome_parser import (
    _fetch_markdown,
    extract_github_links,
    normalize_github_url,
    parse_awesome_list,
)


class TestNormalizeGitHubUrl:
    """Tests for normalize_github_url."""

    def test_standard_url(self) -> None:
        result = normalize_github_url("https://github.com/octocat/hello-world")
        assert result == ("octocat", "hello-world")

    def test_with_trailing_slash(self) -> None:
        result = normalize_github_url("https://github.com/octocat/hello-world/")
        assert result == ("octocat", "hello-world")

    def test_with_git_suffix(self) -> None:
        result = normalize_github_url("https://github.com/octocat/hello-world.git")
        assert result == ("octocat", "hello-world")

    def test_http_url(self) -> None:
        result = normalize_github_url("http://github.com/octocat/hello-world")
        assert result == ("octocat", "hello-world")

    def test_filtered_pages(self) -> None:
        for page in ["features", "pricing", "about", "explore", "topics", "settings"]:
            result = normalize_github_url(f"https://github.com/{page}/something")
            assert result is None, f"Should filter {page}"

    def test_invalid_url(self) -> None:
        assert normalize_github_url("https://example.com/owner/repo") is None

    def test_not_a_url(self) -> None:
        assert normalize_github_url("not a url") is None

    def test_github_user_page_no_repo(self) -> None:
        assert normalize_github_url("https://github.com/octocat") is None

    def test_whitespace_stripped(self) -> None:
        result = normalize_github_url("  https://github.com/owner/repo  ")
        assert result == ("owner", "repo")

    def test_with_query_params(self) -> None:
        result = normalize_github_url("https://github.com/owner/repo?tab=readme")
        assert result is None  # query params make it not match the simple regex

    def test_with_fragment(self) -> None:
        result = normalize_github_url("https://github.com/owner/repo#readme")
        assert result is None  # fragment makes it not match


class TestExtractGitHubLinks:
    """Tests for extract_github_links."""

    def test_simple_link(self) -> None:
        md = "- [Hello](https://github.com/octocat/hello-world) - A test repo"
        links = extract_github_links(md)
        assert len(links) == 1
        url, text, section = links[0]
        assert url == "https://github.com/octocat/hello-world"
        assert text == "Hello"
        assert section is None

    def test_link_with_section(self) -> None:
        md = """## Tools

- [Tool1](https://github.com/org/tool1) - A tool

## Libraries

- [Lib1](https://github.com/org/lib1) - A library
"""
        links = extract_github_links(md)
        assert len(links) == 2
        assert links[0][2] == "Tools"
        assert links[1][2] == "Libraries"

    def test_multiple_links(self) -> None:
        md = """- [A](https://github.com/org/a) - Repo A
- [B](https://github.com/org/b) - Repo B
- [C](https://github.com/org/c) - Repo C
"""
        links = extract_github_links(md)
        assert len(links) == 3

    def test_no_links(self) -> None:
        md = "Just some text with no links."
        links = extract_github_links(md)
        assert links == []

    def test_non_github_links_ignored(self) -> None:
        md = "- [Other](https://example.com/org/repo) - Not GitHub"
        links = extract_github_links(md)
        assert links == []

    def test_nested_sections(self) -> None:
        md = """# Main
## Sub
### Deep
- [Repo](https://github.com/org/repo) - Description
"""
        links = extract_github_links(md)
        assert len(links) == 1
        assert links[0][2] == "Deep"

    def test_badge_link_in_text(self) -> None:
        # Badge links with nested [] break the simple regex — this is a known limitation
        md = "- [Repo ![stars](https://img.shields.io)](https://github.com/org/repo) - Desc"
        links = extract_github_links(md)
        # The [^\]]* pattern stops at the nested ], so this won't match
        assert len(links) == 0

    def test_simple_badge_free_link(self) -> None:
        md = "- [Repo](https://github.com/org/repo) ![stars](https://img.shields.io) - Desc"
        links = extract_github_links(md)
        assert len(links) == 1
        assert links[0][0] == "https://github.com/org/repo"


class TestFetchMarkdown:
    """Tests for _fetch_markdown."""

    @patch("repo_scout.awesome_parser.httpx.get")
    def test_github_url_converts_to_raw(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.text = "# Awesome"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = _fetch_markdown("https://github.com/org/awesome-list")
        assert result == "# Awesome"
        mock_get.assert_called_once_with(
            "https://raw.githubusercontent.com/org/awesome-list/HEAD/README.md",
            timeout=30.0,
            follow_redirects=True,
        )

    @patch("repo_scout.awesome_parser.httpx.get")
    def test_non_github_url_used_directly(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.text = "content"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = _fetch_markdown("https://example.com/list.md")
        assert result == "content"
        mock_get.assert_called_once_with(
            "https://example.com/list.md",
            timeout=30.0,
            follow_redirects=True,
        )

    @patch("repo_scout.awesome_parser.httpx.get")
    def test_http_error_returns_empty(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = httpx.ConnectError("fail")
        result = _fetch_markdown("https://github.com/org/repo")
        assert result == ""

    @patch("repo_scout.awesome_parser.httpx.get")
    def test_raise_for_status_error(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        )
        mock_get.return_value = mock_response

        result = _fetch_markdown("https://github.com/org/repo")
        assert result == ""


class TestParseAwesomeList:
    """Tests for parse_awesome_list."""

    @patch("repo_scout.awesome_parser._fetch_markdown")
    def test_full_parse(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = """# Awesome

## Tools

- [Tool1](https://github.com/org/tool1) - A tool
- [Tool2](https://github.com/org/tool2) - Another tool
"""
        records = parse_awesome_list("https://github.com/org/awesome-list")
        assert len(records) == 2
        assert records[0]["owner"] == "org"
        assert records[0]["name"] == "tool1"
        assert records[0]["sources"] == ["awesome_list"]
        assert records[0]["metadata"]["section"] == "Tools"
        assert records[0]["metadata"]["source_url"] == "https://github.com/org/awesome-list"

    @patch("repo_scout.awesome_parser._fetch_markdown")
    def test_empty_markdown(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = ""
        records = parse_awesome_list("https://github.com/org/awesome")
        assert records == []

    @patch("repo_scout.awesome_parser._fetch_markdown")
    def test_dedup_within_list(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = """- [A](https://github.com/org/repo) - First mention
- [B](https://github.com/org/repo) - Duplicate
"""
        records = parse_awesome_list("https://github.com/org/awesome")
        assert len(records) == 1

    @patch("repo_scout.awesome_parser._fetch_markdown")
    def test_no_section_metadata(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = "- [Repo](https://github.com/org/repo) - Desc"
        records = parse_awesome_list("https://github.com/org/awesome")
        assert len(records) == 1
        assert "section" not in records[0]["metadata"]

    @patch("repo_scout.awesome_parser._fetch_markdown")
    def test_link_text_in_metadata(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = "- [My Tool](https://github.com/org/tool) - Desc"
        records = parse_awesome_list("https://github.com/org/awesome")
        assert records[0]["metadata"]["link_text"] == "My Tool"

    @patch("repo_scout.awesome_parser._fetch_markdown")
    def test_filtered_urls_excluded(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = (
            "- [Features](https://github.com/features/something) - Not a repo\n"
            "- [Real](https://github.com/org/real) - A repo"
        )
        records = parse_awesome_list("https://github.com/org/awesome")
        # "features/something" won't match _GITHUB_LINK_RE since the regex requires
        # the link to be in the format github.com/owner/repo, and the link format
        # in extract_github_links is different from normalize_github_url.
        # The normalize step will filter it.
        for r in records:
            assert r["owner"] != "features"
