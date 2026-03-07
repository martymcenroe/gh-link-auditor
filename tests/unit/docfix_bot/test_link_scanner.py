"""Tests for docfix_bot.link_scanner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from docfix_bot.config import get_default_config
from docfix_bot.link_scanner import (
    check_link,
    extract_links_from_markdown,
    scan_repository,
    suggest_fix,
)
from docfix_bot.models import make_target


class TestExtractLinksFromMarkdown:
    def test_markdown_links(self) -> None:
        content = "Check [Example](https://example.com) and [Python](https://python.org)."
        links = extract_links_from_markdown(content)
        assert len(links) == 2
        assert links[0] == ("https://example.com", 1)
        assert links[1] == ("https://python.org", 1)

    def test_line_numbers(self) -> None:
        content = "Line 1\n[Link](https://example.com)\nLine 3\n"
        links = extract_links_from_markdown(content)
        assert links[0][1] == 2

    def test_bare_urls(self) -> None:
        content = "Visit https://example.com for more."
        links = extract_links_from_markdown(content)
        assert len(links) == 1
        assert links[0][0] == "https://example.com"

    def test_dedup(self) -> None:
        content = "[A](https://example.com) [B](https://example.com)"
        links = extract_links_from_markdown(content)
        assert len(links) == 1

    def test_no_links(self) -> None:
        links = extract_links_from_markdown("Just plain text.")
        assert links == []

    def test_non_http_links_ignored(self) -> None:
        content = "[Email](mailto:user@example.com) [File](./local.md)"
        links = extract_links_from_markdown(content)
        assert links == []

    def test_multiple_lines(self) -> None:
        content = """# Title

- [A](https://a.com) description
- [B](https://b.com) description

See https://c.com for details.
"""
        links = extract_links_from_markdown(content)
        assert len(links) == 3


class TestCheckLink:
    @patch("docfix_bot.link_scanner.validate_ip_safety")
    @patch("docfix_bot.link_scanner.httpx.head")
    def test_working_link(self, mock_head: MagicMock, mock_validate: MagicMock) -> None:
        mock_validate.return_value = {"is_safe": True, "url": "", "resolved_ip": None, "rejection_reason": None}
        mock_head.return_value = MagicMock(status_code=200)
        config = get_default_config()
        status, error = check_link("https://example.com", config)
        assert status == 200
        assert error is None

    @patch("docfix_bot.link_scanner.validate_ip_safety")
    @patch("docfix_bot.link_scanner.httpx.head")
    def test_broken_404(self, mock_head: MagicMock, mock_validate: MagicMock) -> None:
        mock_validate.return_value = {"is_safe": True, "url": "", "resolved_ip": None, "rejection_reason": None}
        mock_head.return_value = MagicMock(status_code=404)
        config = get_default_config()
        status, error = check_link("https://example.com/missing", config)
        assert status == 404

    @patch("docfix_bot.link_scanner.validate_ip_safety")
    def test_ssrf_blocked(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = {
            "is_safe": False,
            "url": "",
            "resolved_ip": "127.0.0.1",
            "rejection_reason": "Private IP",
        }
        config = get_default_config()
        status, error = check_link("http://localhost/secret", config)
        assert status == 0
        assert "SSRF" in error

    @patch("docfix_bot.link_scanner.validate_ip_safety")
    @patch("docfix_bot.link_scanner.httpx.head")
    @patch("docfix_bot.link_scanner.httpx.get")
    def test_antibot_retry(self, mock_get: MagicMock, mock_head: MagicMock, mock_validate: MagicMock) -> None:
        mock_validate.return_value = {"is_safe": True, "url": "", "resolved_ip": None, "rejection_reason": None}
        mock_head.return_value = MagicMock(status_code=403)
        mock_get.return_value = MagicMock(status_code=200)
        config = get_default_config()
        status, error = check_link("https://example.com", config)
        assert status == 200
        mock_get.assert_called_once()

    @patch("docfix_bot.link_scanner.validate_ip_safety")
    @patch("docfix_bot.link_scanner.httpx.head")
    def test_timeout_retries(self, mock_head: MagicMock, mock_validate: MagicMock) -> None:
        mock_validate.return_value = {"is_safe": True, "url": "", "resolved_ip": None, "rejection_reason": None}
        mock_head.side_effect = httpx.ReadTimeout("timeout")
        config = get_default_config()
        status, error = check_link("https://slow.example.com", config, max_retries=2)
        assert status == 0
        assert "Timeout" in error

    @patch("docfix_bot.link_scanner.validate_ip_safety")
    @patch("docfix_bot.link_scanner.httpx.head")
    def test_connection_error(self, mock_head: MagicMock, mock_validate: MagicMock) -> None:
        mock_validate.return_value = {"is_safe": True, "url": "", "resolved_ip": None, "rejection_reason": None}
        mock_head.side_effect = httpx.ConnectError("fail")
        config = get_default_config()
        status, error = check_link("https://down.example.com", config, max_retries=1)
        assert status == 0

    @patch("docfix_bot.link_scanner.time.sleep")
    @patch("docfix_bot.link_scanner.validate_ip_safety")
    @patch("docfix_bot.link_scanner.httpx.head")
    def test_http_error_retries_then_fails(
        self, mock_head: MagicMock, mock_validate: MagicMock, mock_sleep: MagicMock
    ) -> None:
        mock_validate.return_value = {"is_safe": True, "url": "", "resolved_ip": None, "rejection_reason": None}
        mock_head.side_effect = httpx.ConnectError("fail")
        config = get_default_config()
        status, error = check_link("https://down.example.com", config, max_retries=2)
        assert status == 0
        # Should have retried (slept between attempts)
        mock_sleep.assert_called()


class TestSuggestFix:
    @patch("docfix_bot.link_scanner.httpx.get")
    def test_archive_found(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "archived_snapshots": {
                    "closest": {
                        "available": True,
                        "url": "https://web.archive.org/web/123/https://old.com",
                    }
                }
            },
        )
        url, confidence = suggest_fix("https://old.com")
        assert url is not None
        assert "archive.org" in url
        assert confidence > 0.0

    @patch("docfix_bot.link_scanner.httpx.get")
    def test_no_archive(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"archived_snapshots": {}},
        )
        url, confidence = suggest_fix("https://gone.com")
        assert url is None
        assert confidence == 0.0

    @patch("docfix_bot.link_scanner.httpx.get")
    def test_api_error(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = httpx.ConnectError("fail")
        url, confidence = suggest_fix("https://error.com")
        assert url is None
        assert confidence == 0.0


class TestScanRepository:
    @patch("docfix_bot.link_scanner.check_link")
    @patch("docfix_bot.link_scanner.suggest_fix")
    def test_finds_broken_links(self, mock_suggest: MagicMock, mock_check: MagicMock, tmp_path: Path) -> None:
        # Create a markdown file with a link
        md_file = tmp_path / "README.md"
        md_file.write_text("[Test](https://example.com/broken)\n")

        mock_check.return_value = (404, None)
        mock_suggest.return_value = (None, 0.0)

        target = make_target("org", "repo")
        config = get_default_config()
        result = scan_repository(target, config, tmp_path)

        assert result["files_scanned"] == 1
        assert result["links_checked"] == 1
        assert len(result["broken_links"]) == 1
        assert result["broken_links"][0]["status_code"] == 404

    @patch("docfix_bot.link_scanner.check_link")
    def test_no_broken_links(self, mock_check: MagicMock, tmp_path: Path) -> None:
        md_file = tmp_path / "README.md"
        md_file.write_text("[OK](https://example.com)\n")
        mock_check.return_value = (200, None)

        target = make_target("org", "repo")
        result = scan_repository(target, get_default_config(), tmp_path)
        assert len(result["broken_links"]) == 0

    def test_empty_repo(self, tmp_path: Path) -> None:
        target = make_target("org", "repo")
        result = scan_repository(target, get_default_config(), tmp_path)
        assert result["files_scanned"] == 0
        assert result["links_checked"] == 0

    @patch("docfix_bot.link_scanner.check_link")
    def test_connection_error_logged(self, mock_check: MagicMock, tmp_path: Path) -> None:
        md_file = tmp_path / "README.md"
        md_file.write_text("[Link](https://example.com)\n")
        mock_check.return_value = (0, "Connection error")

        target = make_target("org", "repo")
        result = scan_repository(target, get_default_config(), tmp_path)
        assert len(result["broken_links"]) == 0  # Connection errors aren't "broken"

    def test_unreadable_file(self, tmp_path: Path) -> None:
        md_file = tmp_path / "README.md"
        md_file.write_text("content")

        target = make_target("org", "repo")
        # Mock read_text to raise OSError
        with patch.object(Path, "read_text", side_effect=OSError("Permission denied")):
            result = scan_repository(target, get_default_config(), tmp_path)
        assert result["files_scanned"] == 0
