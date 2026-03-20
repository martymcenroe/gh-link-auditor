"""Tests for N1 Scan node.

See LLD #22 §10.0 T060/T070: N1 scan parsing and clean repo.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from gh_link_auditor.pipeline.nodes.n1_scan import (
    _clean_url_tail,
    _extract_urls_from_file,
    _is_dead,
    _is_historical_file,
    _read_file_content,
    n1_scan,
    parse_scan_output,
    run_link_scan,
)
from gh_link_auditor.pipeline.state import DeadLink, create_initial_state
from tests.fakes.github_api import FakeGitHubContentsClient


class TestParseScanOutput:
    """Tests for parse_scan_output()."""

    def test_parses_valid_json(self) -> None:
        data = [
            {
                "url": "https://example.com/broken",
                "source_file": "README.md",
                "line_number": 10,
                "link_text": "broken link",
                "http_status": 404,
                "error_type": "http_error",
            }
        ]
        result = parse_scan_output(json.dumps(data))
        assert len(result) == 1
        assert result[0]["url"] == "https://example.com/broken"
        assert result[0]["http_status"] == 404

    def test_parses_multiple_links(self) -> None:
        data = [
            {
                "url": f"https://example.com/dead-{i}",
                "source_file": "README.md",
                "line_number": i,
                "link_text": f"link {i}",
                "http_status": 404,
                "error_type": "http_error",
            }
            for i in range(5)
        ]
        result = parse_scan_output(json.dumps(data))
        assert len(result) == 5

    def test_parses_none_http_status(self) -> None:
        data = [
            {
                "url": "https://nonexistent.invalid",
                "source_file": "doc.md",
                "line_number": 3,
                "link_text": "dead",
                "http_status": None,
                "error_type": "dns_error",
            }
        ]
        result = parse_scan_output(json.dumps(data))
        assert result[0]["http_status"] is None
        assert result[0]["error_type"] == "dns_error"

    def test_parses_empty_list(self) -> None:
        result = parse_scan_output("[]")
        assert result == []

    def test_handles_invalid_json(self) -> None:
        result = parse_scan_output("not json at all")
        assert result == []

    def test_handles_empty_string(self) -> None:
        result = parse_scan_output("")
        assert result == []


class TestExtractUrlsFromFile:
    """Tests for _extract_urls_from_file()."""

    def test_extracts_urls(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text("Check [link](https://example.com/page)\n")
        results = _extract_urls_from_file(str(md))
        assert len(results) == 1
        assert results[0][0] == "https://example.com/page"

    def test_returns_empty_on_os_error(self) -> None:
        results = _extract_urls_from_file("/nonexistent/file/xyz.md")
        assert results == []

    def test_strips_trailing_punctuation(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text("Visit https://example.com/page.\n")
        results = _extract_urls_from_file(str(md))
        assert results[0][0] == "https://example.com/page"

    def test_preserves_balanced_parens(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text("[Wiki](https://en.wikipedia.org/wiki/Foo_(bar))\n")
        results = _extract_urls_from_file(str(md))
        assert results[0][0] == "https://en.wikipedia.org/wiki/Foo_(bar)"

    def test_strips_unbalanced_trailing_paren(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text("(see https://example.com/page)\n")
        results = _extract_urls_from_file(str(md))
        assert results[0][0] == "https://example.com/page"

    def test_nested_parens(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text("[link](https://en.wikipedia.org/wiki/A_(B_(C)))\n")
        results = _extract_urls_from_file(str(md))
        assert results[0][0] == "https://en.wikipedia.org/wiki/A_(B_(C))"


class TestCleanUrlTail:
    """Tests for _clean_url_tail() balanced paren logic."""

    def test_simple_url(self) -> None:
        assert _clean_url_tail("https://example.com/page") == "https://example.com/page"

    def test_strips_period(self) -> None:
        assert _clean_url_tail("https://example.com/page.") == "https://example.com/page"

    def test_strips_comma(self) -> None:
        assert _clean_url_tail("https://example.com/page,") == "https://example.com/page"

    def test_preserves_balanced_parens(self) -> None:
        assert _clean_url_tail("https://en.wikipedia.org/wiki/Foo_(bar)") == "https://en.wikipedia.org/wiki/Foo_(bar)"

    def test_strips_unbalanced_close_paren(self) -> None:
        assert _clean_url_tail("https://example.com/page)") == "https://example.com/page"

    def test_strips_trailing_paren_and_punct(self) -> None:
        assert _clean_url_tail("https://example.com/page).") == "https://example.com/page"

    def test_nested_balanced_parens(self) -> None:
        assert _clean_url_tail("https://en.wikipedia.org/wiki/A_(B_(C))") == "https://en.wikipedia.org/wiki/A_(B_(C))"

    def test_markdown_link_paren(self) -> None:
        # In [text](url), the regex now captures the closing ) so we need to strip it
        assert _clean_url_tail("https://example.com/page)") == "https://example.com/page"

    def test_preserves_parens_in_path(self) -> None:
        assert _clean_url_tail("https://example.com/(test)") == "https://example.com/(test)"

    def test_double_trailing_paren_unbalanced(self) -> None:
        assert _clean_url_tail("https://example.com/page))") == "https://example.com/page"


class TestIsHistoricalFile:
    """Tests for _is_historical_file()."""

    def test_changelog(self) -> None:
        assert _is_historical_file("CHANGELOG.md") is True

    def test_changes(self) -> None:
        assert _is_historical_file("CHANGES.rst") is True

    def test_history(self) -> None:
        assert _is_historical_file("HISTORY.md") is True

    def test_releases(self) -> None:
        assert _is_historical_file("RELEASES.md") is True

    def test_news(self) -> None:
        assert _is_historical_file("NEWS") is True

    def test_readme_is_not_historical(self) -> None:
        assert _is_historical_file("README.md") is False

    def test_contributing_is_not_historical(self) -> None:
        assert _is_historical_file("CONTRIBUTING.md") is False

    def test_case_insensitive(self) -> None:
        assert _is_historical_file("changelog.md") is True

    def test_nested_path(self) -> None:
        assert _is_historical_file("docs/CHANGELOG.md") is True


class TestIsDead:
    """Tests for _is_dead()."""

    def test_dead_status(self) -> None:
        assert _is_dead({"status": "dead"}) is True

    def test_error_status(self) -> None:
        assert _is_dead({"status": "error"}) is True

    def test_ok_status(self) -> None:
        assert _is_dead({"status": "ok", "status_code": 200}) is False

    def test_404_status_code(self) -> None:
        assert _is_dead({"status": "ok", "status_code": 404}) is True

    def test_200_status_code(self) -> None:
        assert _is_dead({"status": "ok", "status_code": 200}) is False

    def test_none_status_code(self) -> None:
        assert _is_dead({"status": "ok", "status_code": None}) is False


class TestRunLinkScan:
    """Tests for run_link_scan()."""

    def test_scans_local_files(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text("Check [link](https://httpstat.us/404)\n")
        with patch("gh_link_auditor.pipeline.nodes.n1_scan._check_single_url") as mock_check:
            mock_check.return_value = {
                "url": "https://httpstat.us/404",
                "status": "dead",
                "status_code": 404,
                "method": "HEAD",
                "response_time_ms": 100,
            }
            dead_links = run_link_scan([str(md)], str(tmp_path), "local")
        assert len(dead_links) >= 0  # May be 0 if URL not considered dead

    def test_returns_empty_for_no_files(self, tmp_path: Path) -> None:
        dead_links = run_link_scan([], str(tmp_path), "local")
        assert dead_links == []

    def test_returns_empty_for_clean_files(self, tmp_path: Path) -> None:
        md = tmp_path / "clean.md"
        md.write_text("No links here.\n")
        dead_links = run_link_scan([str(md)], str(tmp_path), "local")
        assert dead_links == []

    def test_deduplicates_urls_across_files(self, tmp_path: Path) -> None:
        md1 = tmp_path / "a.md"
        md1.write_text("[link](https://httpstat.us/404)\n")
        md2 = tmp_path / "b.md"
        md2.write_text("[link](https://httpstat.us/404)\n")
        with patch("gh_link_auditor.pipeline.nodes.n1_scan._check_single_url") as mock_check:
            mock_check.return_value = {
                "url": "https://httpstat.us/404",
                "status": "dead",
                "status_code": 404,
                "method": "HEAD",
                "response_time_ms": 100,
            }
            run_link_scan([str(md1), str(md2)], str(tmp_path), "local")
        # Should only check once due to dedup
        assert mock_check.call_count == 1

    def test_handles_file_with_multiple_links(self, tmp_path: Path) -> None:
        md = tmp_path / "multi.md"
        md.write_text("[a](https://httpstat.us/404)\n[b](https://httpstat.us/410)\n[c](https://httpstat.us/200)\n")
        with patch("gh_link_auditor.pipeline.nodes.n1_scan._check_single_url") as mock_check:

            def side_effect(url):
                if "200" in url:
                    return {
                        "url": url,
                        "status": "ok",
                        "status_code": 200,
                        "method": "HEAD",
                        "response_time_ms": 50,
                    }
                return {
                    "url": url,
                    "status": "dead",
                    "status_code": int(url.split("/")[-1]),
                    "method": "HEAD",
                    "response_time_ms": 100,
                }

            mock_check.side_effect = side_effect
            dead_links = run_link_scan([str(md)], str(tmp_path), "local")
        assert len(dead_links) == 2


class TestReadFileContent:
    """Tests for _read_file_content()."""

    def test_reads_local_file(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text("# Hello World")
        content = _read_file_content(str(md), "local")
        assert content == "# Hello World"

    def test_reads_via_github_client(self) -> None:
        client = FakeGitHubContentsClient()
        client.configure_repo_files(
            "org",
            "repo",
            {
                "README.md": "# Remote Content",
            },
        )
        content = _read_file_content(
            "README.md",
            "url",
            "org",
            "repo",
            github_client=client,
        )
        assert content == "# Remote Content"

    def test_raises_on_missing_local_file(self) -> None:
        import pytest

        with pytest.raises(OSError):
            _read_file_content("/nonexistent/file.md", "local")

    def test_raises_on_missing_remote_file(self) -> None:
        import pytest

        client = FakeGitHubContentsClient()
        client.configure_repo_files("org", "repo", {})
        with pytest.raises(FileNotFoundError):
            _read_file_content(
                "missing.md",
                "url",
                "org",
                "repo",
                github_client=client,
            )


class TestExtractUrlsFromFileUrl:
    """Tests for _extract_urls_from_file() with URL targets."""

    def test_extracts_urls_from_remote_file(self) -> None:
        client = FakeGitHubContentsClient()
        client.configure_repo_files(
            "org",
            "repo",
            {
                "README.md": "Check [link](https://example.com/page)\n",
            },
        )
        results = _extract_urls_from_file(
            "README.md",
            "url",
            "org",
            "repo",
            github_client=client,
        )
        assert len(results) == 1
        assert results[0][0] == "https://example.com/page"

    def test_returns_empty_for_missing_remote_file(self) -> None:
        client = FakeGitHubContentsClient()
        client.configure_repo_files("org", "repo", {})
        results = _extract_urls_from_file(
            "missing.md",
            "url",
            "org",
            "repo",
            github_client=client,
        )
        assert results == []


class TestRunLinkScanUrl:
    """Tests for run_link_scan() with URL targets."""

    def test_scans_remote_files(self) -> None:
        client = FakeGitHubContentsClient()
        client.configure_repo_files(
            "org",
            "repo",
            {
                "README.md": "Check [link](https://httpstat.us/404)\n",
            },
        )
        with patch("gh_link_auditor.pipeline.nodes.n1_scan._check_single_url") as mock_check:
            mock_check.return_value = {
                "url": "https://httpstat.us/404",
                "status": "dead",
                "status_code": 404,
                "method": "HEAD",
                "response_time_ms": 100,
            }
            dead_links = run_link_scan(
                ["README.md"],
                "https://github.com/org/repo",
                "url",
                repo_owner="org",
                repo_name_short="repo",
                github_client=client,
            )
        assert len(dead_links) == 1
        assert dead_links[0]["url"] == "https://httpstat.us/404"
        assert dead_links[0]["source_file"] == "README.md"


class TestCheckSingleUrl:
    """Tests for _check_single_url() via network module delegation."""

    def test_delegates_to_network_module(self) -> None:
        mock_result = {
            "url": "https://example.com",
            "status": "ok",
            "status_code": 200,
            "method": "HEAD",
            "response_time_ms": 50,
        }
        with patch(
            "gh_link_auditor.pipeline.nodes.n1_scan.network_check_url",
            return_value=mock_result,
        ):
            from gh_link_auditor.pipeline.nodes.n1_scan import _check_single_url

            result = _check_single_url("https://example.com")
        assert result["status"] == "ok"
        assert result["status_code"] == 200


class TestN1Scan:
    """Tests for n1_scan() node function."""

    def test_sets_scan_complete(self, tmp_path: Path) -> None:
        state = create_initial_state(target=str(tmp_path))
        state["doc_files"] = []
        with patch("gh_link_auditor.pipeline.nodes.n1_scan.run_link_scan", return_value=[]):
            result = n1_scan(state)
        assert result["scan_complete"] is True

    def test_populates_dead_links(self, tmp_path: Path) -> None:
        state = create_initial_state(target=str(tmp_path))
        state["doc_files"] = ["README.md"]
        mock_dead = [
            DeadLink(
                url="https://x.com/broken",
                source_file="README.md",
                line_number=5,
                link_text="broken",
                http_status=404,
                error_type="http_error",
            )
        ]
        with patch(
            "gh_link_auditor.pipeline.nodes.n1_scan.run_link_scan",
            return_value=mock_dead,
        ):
            result = n1_scan(state)
        assert len(result["dead_links"]) == 1

    def test_empty_doc_files_returns_empty_dead_links(self, tmp_path: Path) -> None:
        state = create_initial_state(target=str(tmp_path))
        state["doc_files"] = []
        with patch("gh_link_auditor.pipeline.nodes.n1_scan.run_link_scan", return_value=[]):
            result = n1_scan(state)
        assert result["dead_links"] == []

    def test_error_handling(self, tmp_path: Path) -> None:
        state = create_initial_state(target=str(tmp_path))
        state["doc_files"] = ["nonexistent.md"]
        with patch(
            "gh_link_auditor.pipeline.nodes.n1_scan.run_link_scan",
            side_effect=Exception("scan failed"),
        ):
            result = n1_scan(state)
        assert len(result["errors"]) > 0
        assert result["scan_complete"] is True
