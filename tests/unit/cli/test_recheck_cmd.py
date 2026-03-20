"""Tests for the ghla recheck CLI command.

Tests cover argument parsing, dry-run mode, URL recheck logic
(resolved, confirmed dead, re-snoozed), and summary output.

See issue #148 for specification.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from gh_link_auditor.cli.main import build_parser
from gh_link_auditor.cli.recheck_cmd import cmd_recheck
from gh_link_auditor.unified_db import UnifiedDatabase

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database and return its path."""
    path = str(tmp_path / "test.db")
    with UnifiedDatabase(path):
        pass
    return path


@pytest.fixture
def db_with_due_entry(db_path):
    """Create a DB with one due recheck entry."""
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with UnifiedDatabase(db_path) as db:
        db._conn.execute(
            """INSERT INTO recheck_queue
            (url, repo_full_name, source_file, recheck_count, last_status,
             last_checked_at, snooze_until, reason, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                "https://example.com/dead",
                "owner/repo",
                "README.md",
                0,
                "snoozed",
                past,
                past,
                None,
                past,
            ),
        )
        db._conn.commit()
    return db_path


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestRecheckParser:
    """Tests for recheck subcommand parser registration."""

    def test_recheck_subcommand_exists(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["recheck"])
        assert args.command == "recheck"

    def test_db_path_argument(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["recheck", "--db-path", "/tmp/test.db"])
        assert args.db_path == "/tmp/test.db"

    def test_dry_run_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["recheck", "--dry-run"])
        assert args.dry_run is True

    def test_default_no_dry_run(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["recheck"])
        assert args.dry_run is False


# ---------------------------------------------------------------------------
# cmd_recheck tests
# ---------------------------------------------------------------------------


class TestCmdRecheck:
    """Tests for cmd_recheck() function."""

    def test_no_due_rechecks(self, db_path, capsys) -> None:
        """Empty queue prints 'No rechecks due.'"""
        args = argparse.Namespace(db_path=db_path, dry_run=False)
        result = cmd_recheck(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "No rechecks due" in captured.out

    def test_dry_run_does_not_modify(self, db_with_due_entry, capsys) -> None:
        """Dry run should not change the database."""
        args = argparse.Namespace(db_path=db_with_due_entry, dry_run=True)
        result = cmd_recheck(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "dry-run" in captured.out

        # Entry should still be snoozed
        with UnifiedDatabase(db_with_due_entry) as db:
            row = db._conn.execute("SELECT last_status FROM recheck_queue").fetchone()
            assert row["last_status"] == "snoozed"

    def test_resolved_when_url_live(self, db_with_due_entry, capsys) -> None:
        """URL returning 200 should be marked resolved."""
        fake_result = {
            "url": "https://example.com/dead",
            "status": "ok",
            "status_code": 200,
            "method": "HEAD",
            "response_time_ms": 100,
            "retries": 0,
            "error": None,
        }
        args = argparse.Namespace(db_path=db_with_due_entry, dry_run=False)
        with patch("gh_link_auditor.cli.recheck_cmd._check_url", return_value=fake_result):
            result = cmd_recheck(args)
        assert result == 0

        with UnifiedDatabase(db_with_due_entry) as db:
            row = db._conn.execute("SELECT last_status FROM recheck_queue").fetchone()
            assert row["last_status"] == "resolved"

        captured = capsys.readouterr()
        assert "RESOLVED" in captured.out
        assert "Resolved:       1" in captured.out

    def test_re_snoozed_when_still_dead(self, db_with_due_entry, capsys) -> None:
        """URL still dead (recheck_count < 2) should be re-snoozed."""
        fake_result = {
            "url": "https://example.com/dead",
            "status": "error",
            "status_code": 404,
            "method": "HEAD",
            "response_time_ms": 100,
            "retries": 0,
            "error": "Not Found",
        }
        args = argparse.Namespace(db_path=db_with_due_entry, dry_run=False)
        with patch("gh_link_auditor.cli.recheck_cmd._check_url", return_value=fake_result):
            result = cmd_recheck(args)
        assert result == 0

        with UnifiedDatabase(db_with_due_entry) as db:
            row = db._conn.execute("SELECT last_status, recheck_count FROM recheck_queue").fetchone()
            assert row["last_status"] == "snoozed"
            assert row["recheck_count"] == 1

        captured = capsys.readouterr()
        assert "re-snoozed" in captured.out
        assert "Re-snoozed:     1" in captured.out

    def test_confirmed_dead_after_3_checks(self, db_path, capsys) -> None:
        """URL still dead with recheck_count >= 2 should be confirmed dead."""
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with UnifiedDatabase(db_path) as db:
            db._conn.execute(
                """INSERT INTO recheck_queue
                (url, repo_full_name, source_file, recheck_count, last_status,
                 last_checked_at, snooze_until, reason, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    "https://example.com/dead",
                    "owner/repo",
                    "README.md",
                    2,  # Already checked twice
                    "snoozed",
                    past,
                    past,
                    None,
                    past,
                ),
            )
            db._conn.commit()

        fake_result = {
            "url": "https://example.com/dead",
            "status": "error",
            "status_code": 404,
            "method": "HEAD",
            "response_time_ms": 100,
            "retries": 0,
            "error": "Not Found",
        }
        args = argparse.Namespace(db_path=db_path, dry_run=False)
        with patch("gh_link_auditor.cli.recheck_cmd._check_url", return_value=fake_result):
            result = cmd_recheck(args)
        assert result == 0

        with UnifiedDatabase(db_path) as db:
            row = db._conn.execute("SELECT last_status FROM recheck_queue").fetchone()
            assert row["last_status"] == "confirmed_dead"

        captured = capsys.readouterr()
        assert "CONFIRMED DEAD" in captured.out

    def test_multiple_entries(self, db_path, capsys) -> None:
        """Multiple due entries should all be processed."""
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with UnifiedDatabase(db_path) as db:
            for url in ["https://a.com/dead", "https://b.com/dead"]:
                db._conn.execute(
                    """INSERT INTO recheck_queue
                    (url, repo_full_name, source_file, recheck_count, last_status,
                     last_checked_at, snooze_until, reason, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (url, "o/r", "README.md", 0, "snoozed", past, past, None, past),
                )
            db._conn.commit()

        fake_result_live = {
            "url": "https://a.com/dead",
            "status": "ok",
            "status_code": 200,
            "method": "HEAD",
            "response_time_ms": 100,
            "retries": 0,
            "error": None,
        }
        fake_result_dead = {
            "url": "https://b.com/dead",
            "status": "error",
            "status_code": 404,
            "method": "HEAD",
            "response_time_ms": 100,
            "retries": 0,
            "error": "Not Found",
        }
        args = argparse.Namespace(db_path=db_path, dry_run=False)
        with patch(
            "gh_link_auditor.cli.recheck_cmd._check_url",
            side_effect=[fake_result_live, fake_result_dead],
        ):
            result = cmd_recheck(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "Resolved:       1" in captured.out
        assert "Re-snoozed:     1" in captured.out

    def test_shows_queue_stats(self, db_with_due_entry, capsys) -> None:
        """Output should include queue stats section."""
        fake_result = {
            "url": "https://example.com/dead",
            "status": "ok",
            "status_code": 200,
            "method": "HEAD",
            "response_time_ms": 100,
            "retries": 0,
            "error": None,
        }
        args = argparse.Namespace(db_path=db_with_due_entry, dry_run=False)
        with patch("gh_link_auditor.cli.recheck_cmd._check_url", return_value=fake_result):
            cmd_recheck(args)

        captured = capsys.readouterr()
        assert "Queue Stats" in captured.out

    def test_url_with_none_status_code_treated_as_dead(self, db_with_due_entry, capsys) -> None:
        """A result with status_code=None should be treated as dead."""
        fake_result = {
            "url": "https://example.com/dead",
            "status": "error",
            "status_code": None,
            "method": "HEAD",
            "response_time_ms": None,
            "retries": 3,
            "error": "DNS resolution failed",
        }
        args = argparse.Namespace(db_path=db_with_due_entry, dry_run=False)
        with patch("gh_link_auditor.cli.recheck_cmd._check_url", return_value=fake_result):
            result = cmd_recheck(args)
        assert result == 0

        with UnifiedDatabase(db_with_due_entry) as db:
            row = db._conn.execute("SELECT last_status, recheck_count FROM recheck_queue").fetchone()
            assert row["last_status"] == "snoozed"
            assert row["recheck_count"] == 1

    def test_status_301_treated_as_live(self, db_with_due_entry, capsys) -> None:
        """HTTP 301 should be treated as live (redirect means resource exists)."""
        fake_result = {
            "url": "https://example.com/dead",
            "status": "ok",
            "status_code": 301,
            "method": "HEAD",
            "response_time_ms": 100,
            "retries": 0,
            "error": None,
        }
        args = argparse.Namespace(db_path=db_with_due_entry, dry_run=False)
        with patch("gh_link_auditor.cli.recheck_cmd._check_url", return_value=fake_result):
            result = cmd_recheck(args)
        assert result == 0

        with UnifiedDatabase(db_with_due_entry) as db:
            row = db._conn.execute("SELECT last_status FROM recheck_queue").fetchone()
            assert row["last_status"] == "resolved"
