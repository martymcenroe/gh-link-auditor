"""Tests for automated maintainer blacklisting.

Covers pr_tracker auto-blacklist signals, N0 blacklist check,
unified_db blacklist-by-source, and CLI blacklist commands.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from gh_link_auditor.metrics.models import PROutcome
from gh_link_auditor.unified_db import UnifiedDatabase

# ---------------------------------------------------------------------------
# UnifiedDatabase: get_blacklist_by_source
# ---------------------------------------------------------------------------


class TestGetBlacklistBySource:
    def test_empty(self):
        with UnifiedDatabase(":memory:") as db:
            assert db.get_blacklist_by_source() == {}

    def test_groups_by_source(self):
        with UnifiedDatabase(":memory:") as db:
            db.add_to_blacklist(repo_url="https://github.com/a/b", source="manual")
            db.add_to_blacklist(repo_url="https://github.com/c/d", source="fix_stolen")
            db.add_to_blacklist(repo_url="https://github.com/e/f", source="fix_stolen")
            result = db.get_blacklist_by_source()
            assert result["manual"] == 1
            assert result["fix_stolen"] == 2

    def test_excludes_expired(self):
        with UnifiedDatabase(":memory:") as db:
            past = datetime.now(timezone.utc) - timedelta(days=1)
            db.add_to_blacklist(repo_url="https://github.com/a/b", source="unresponsive", expires_at=past)
            db.add_to_blacklist(repo_url="https://github.com/c/d", source="manual")
            result = db.get_blacklist_by_source()
            assert "unresponsive" not in result
            assert result["manual"] == 1


# ---------------------------------------------------------------------------
# pr_tracker: auto-blacklist on fix stolen
# ---------------------------------------------------------------------------


class TestAutoBlacklistFixStolen:
    def test_blacklists_on_maintainer_fix(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = UnifiedDatabase(db_path)

        # Record an open PR outcome
        outcome = PROutcome(
            repo_full_name="owner/repo",
            pr_url="https://github.com/owner/repo/pull/1",
            submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            status="open",
        )
        db.record_pr_outcome(outcome)
        db.close()

        # Mock the GitHub API to return closed PR + maintainer fix
        api_data = {"state": "closed", "merged": False, "merged_at": None, "closed_at": "2026-01-05T00:00:00Z"}

        with patch("gh_link_auditor.pr_tracker._fetch_pr_status", return_value=api_data):
            with patch("gh_link_auditor.pr_tracker._check_maintainer_fixed", return_value=True):
                from gh_link_auditor.pr_tracker import refresh_pr_outcomes

                updated = refresh_pr_outcomes(db_path)

        assert len(updated) == 1
        assert updated[0].rejection_reason == "maintainer committed fix directly"

        # Verify blacklist entry was created
        db = UnifiedDatabase(db_path)
        assert db.is_blacklisted("https://github.com/owner/repo")
        by_source = db.get_blacklist_by_source()
        assert by_source.get("fix_stolen", 0) == 1
        db.close()

    def test_no_blacklist_on_normal_close(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = UnifiedDatabase(db_path)

        outcome = PROutcome(
            repo_full_name="owner/repo",
            pr_url="https://github.com/owner/repo/pull/1",
            submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            status="open",
        )
        db.record_pr_outcome(outcome)
        db.close()

        api_data = {"state": "closed", "merged": False, "merged_at": None, "closed_at": "2026-01-05T00:00:00Z"}

        with patch("gh_link_auditor.pr_tracker._fetch_pr_status", return_value=api_data):
            with patch("gh_link_auditor.pr_tracker._check_maintainer_fixed", return_value=False):
                from gh_link_auditor.pr_tracker import refresh_pr_outcomes

                refresh_pr_outcomes(db_path)

        db = UnifiedDatabase(db_path)
        assert not db.is_blacklisted("https://github.com/owner/repo")
        db.close()


# ---------------------------------------------------------------------------
# pr_tracker: unresponsive timeout
# ---------------------------------------------------------------------------


class TestUnresponsiveTimeout:
    def test_blacklists_after_30_days(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = UnifiedDatabase(db_path)

        # PR submitted 31 days ago, still open
        submitted = datetime.now(timezone.utc) - timedelta(days=31)
        outcome = PROutcome(
            repo_full_name="owner/repo",
            pr_url="https://github.com/owner/repo/pull/1",
            submitted_at=submitted,
            status="open",
        )
        db.record_pr_outcome(outcome)
        db.close()

        # API returns still-open
        api_data = {"state": "open", "merged": False, "merged_at": None, "closed_at": None}

        with patch("gh_link_auditor.pr_tracker._fetch_pr_status", return_value=api_data):
            from gh_link_auditor.pr_tracker import refresh_pr_outcomes

            refresh_pr_outcomes(db_path)

        db = UnifiedDatabase(db_path)
        assert db.is_blacklisted("https://github.com/owner/repo")
        by_source = db.get_blacklist_by_source()
        assert by_source.get("unresponsive", 0) == 1
        db.close()

    def test_no_blacklist_before_30_days(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = UnifiedDatabase(db_path)

        submitted = datetime.now(timezone.utc) - timedelta(days=10)
        outcome = PROutcome(
            repo_full_name="owner/repo",
            pr_url="https://github.com/owner/repo/pull/1",
            submitted_at=submitted,
            status="open",
        )
        db.record_pr_outcome(outcome)
        db.close()

        api_data = {"state": "open", "merged": False, "merged_at": None, "closed_at": None}

        with patch("gh_link_auditor.pr_tracker._fetch_pr_status", return_value=api_data):
            from gh_link_auditor.pr_tracker import refresh_pr_outcomes

            refresh_pr_outcomes(db_path)

        db = UnifiedDatabase(db_path)
        assert not db.is_blacklisted("https://github.com/owner/repo")
        db.close()

    def test_no_duplicate_blacklist(self, tmp_path):
        """Running refresh twice doesn't create duplicate entries."""
        db_path = tmp_path / "test.db"
        db = UnifiedDatabase(db_path)

        submitted = datetime.now(timezone.utc) - timedelta(days=31)
        outcome = PROutcome(
            repo_full_name="owner/repo",
            pr_url="https://github.com/owner/repo/pull/1",
            submitted_at=submitted,
            status="open",
        )
        db.record_pr_outcome(outcome)
        db.close()

        api_data = {"state": "open", "merged": False, "merged_at": None, "closed_at": None}

        with patch("gh_link_auditor.pr_tracker._fetch_pr_status", return_value=api_data):
            from gh_link_auditor.pr_tracker import refresh_pr_outcomes

            refresh_pr_outcomes(db_path)
            refresh_pr_outcomes(db_path)

        db = UnifiedDatabase(db_path)
        by_source = db.get_blacklist_by_source()
        assert by_source.get("unresponsive", 0) == 1
        db.close()


# ---------------------------------------------------------------------------
# N0: blacklist check
# ---------------------------------------------------------------------------


class TestN0BlacklistCheck:
    def test_blacklisted_repo_aborts(self, tmp_path):
        from gh_link_auditor.pipeline.nodes.n0_load_target import n0_load_target
        from gh_link_auditor.pipeline.state import create_initial_state

        db_path = str(tmp_path / "test.db")
        db = UnifiedDatabase(db_path)
        db.add_to_blacklist(repo_url="https://github.com/blocked/repo", source="manual")
        db.close()

        state = create_initial_state(target="https://github.com/blocked/repo", db_path=db_path)
        result = n0_load_target(state)

        errors = result.get("errors", [])
        assert any("blacklisted" in e.lower() for e in errors)
        # Should NOT have doc_files since we aborted early
        assert result.get("doc_files") is None or result.get("doc_files") == []

    def test_clean_repo_proceeds(self, tmp_path):
        from gh_link_auditor.pipeline.nodes.n0_load_target import n0_load_target
        from gh_link_auditor.pipeline.state import create_initial_state

        db_path = str(tmp_path / "test.db")
        # Create empty DB (no blacklist entries)
        db = UnifiedDatabase(db_path)
        db.close()

        # Local target so we avoid GitHub API calls
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "README.md").write_text("# Hello\n")

        state = create_initial_state(target=str(tmp_path), db_path=db_path)
        result = n0_load_target(state)

        errors = result.get("errors", [])
        assert not any("blacklisted" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# CLI: blacklist commands
# ---------------------------------------------------------------------------


class TestBlacklistCli:
    def test_list_empty(self, tmp_path):
        from gh_link_auditor.cli.blacklist_cmd import _cmd_list

        db_path = str(tmp_path / "test.db")
        UnifiedDatabase(db_path).close()

        args = type("Args", (), {"db_path": db_path})()
        assert _cmd_list(args) == 0

    def test_add_and_list(self, tmp_path):
        from gh_link_auditor.cli.blacklist_cmd import _cmd_add, _cmd_list

        db_path = str(tmp_path / "test.db")
        UnifiedDatabase(db_path).close()

        args = type("Args", (), {"db_path": db_path, "repo_url": "https://github.com/a/b", "reason": "test"})()
        assert _cmd_add(args) == 0

        args2 = type("Args", (), {"db_path": db_path})()
        assert _cmd_list(args2) == 0

    def test_remove(self, tmp_path):
        from gh_link_auditor.cli.blacklist_cmd import _cmd_add, _cmd_remove

        db_path = str(tmp_path / "test.db")
        UnifiedDatabase(db_path).close()

        args = type("Args", (), {"db_path": db_path, "repo_url": "https://github.com/a/b", "reason": "test"})()
        _cmd_add(args)

        rm_args = type("Args", (), {"db_path": db_path, "entry_id": 1})()
        assert _cmd_remove(rm_args) == 0

    def test_remove_nonexistent(self, tmp_path):
        from gh_link_auditor.cli.blacklist_cmd import _cmd_remove

        db_path = str(tmp_path / "test.db")
        UnifiedDatabase(db_path).close()

        args = type("Args", (), {"db_path": db_path, "entry_id": 999})()
        assert _cmd_remove(args) == 1

    def test_stats(self, tmp_path):
        from gh_link_auditor.cli.blacklist_cmd import _cmd_stats

        db_path = str(tmp_path / "test.db")
        db = UnifiedDatabase(db_path)
        db.add_to_blacklist(repo_url="https://github.com/a/b", source="fix_stolen")
        db.add_to_blacklist(repo_url="https://github.com/c/d", source="manual")
        db.close()

        args = type("Args", (), {"db_path": db_path})()
        assert _cmd_stats(args) == 0
