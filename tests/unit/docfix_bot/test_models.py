"""Tests for docfix_bot.models."""

from __future__ import annotations

from datetime import datetime, timezone

from docfix_bot.models import (
    BotConfig,
    BotState,
    PRSubmission,
    ScanResult,
    TargetRepository,
    URLValidationResult,
    make_broken_link,
    make_target,
    now_iso,
)


class TestMakeTarget:
    def test_basic(self) -> None:
        t = make_target("org", "repo")
        assert t["owner"] == "org"
        assert t["repo"] == "repo"
        assert t["priority"] == 5
        assert t["enabled"] is True
        assert t["last_scanned"] is None

    def test_custom_priority(self) -> None:
        t = make_target("org", "repo", priority=10)
        assert t["priority"] == 10

    def test_disabled(self) -> None:
        t = make_target("org", "repo", enabled=False)
        assert t["enabled"] is False


class TestMakeBrokenLink:
    def test_basic(self) -> None:
        bl = make_broken_link("README.md", 5, "https://example.com", 404)
        assert bl["source_file"] == "README.md"
        assert bl["line_number"] == 5
        assert bl["original_url"] == "https://example.com"
        assert bl["status_code"] == 404
        assert bl["suggested_fix"] is None
        assert bl["fix_confidence"] == 0.0

    def test_with_fix(self) -> None:
        bl = make_broken_link(
            "doc.md", 10, "https://old.com", 404,
            suggested_fix="https://new.com", fix_confidence=0.9,
        )
        assert bl["suggested_fix"] == "https://new.com"
        assert bl["fix_confidence"] == 0.9


class TestNowIso:
    def test_returns_iso_string(self) -> None:
        result = now_iso()
        dt = datetime.fromisoformat(result)
        assert dt.tzinfo == timezone.utc

    def test_is_utc(self) -> None:
        result = now_iso()
        assert "+" in result or "Z" in result


class TestTypedDicts:
    def test_target_repository(self) -> None:
        t: TargetRepository = {
            "owner": "o", "repo": "r", "priority": 1,
            "last_scanned": None, "enabled": True,
        }
        assert t["owner"] == "o"

    def test_scan_result(self) -> None:
        t = make_target("o", "r")
        sr: ScanResult = {
            "repository": t, "scan_time": now_iso(),
            "broken_links": [], "error": None,
            "files_scanned": 0, "links_checked": 0,
        }
        assert sr["files_scanned"] == 0

    def test_pr_submission(self) -> None:
        t = make_target("o", "r")
        pr: PRSubmission = {
            "repository": t, "branch_name": "fix/test",
            "pr_number": 1, "pr_url": "https://github.com",
            "status": "submitted", "broken_links_fixed": [],
            "submitted_at": now_iso(),
        }
        assert pr["status"] == "submitted"

    def test_bot_state(self) -> None:
        bs: BotState = {
            "last_run": now_iso(), "total_prs_submitted": 0,
            "total_links_fixed": 0,
        }
        assert bs["total_prs_submitted"] == 0

    def test_url_validation_result(self) -> None:
        vr: URLValidationResult = {
            "url": "https://example.com", "is_safe": True,
            "resolved_ip": "93.184.216.34", "rejection_reason": None,
        }
        assert vr["is_safe"] is True

    def test_bot_config(self) -> None:
        bc: BotConfig = {"github_token": "test", "http_timeout": 5.0}
        assert bc["http_timeout"] == 5.0
