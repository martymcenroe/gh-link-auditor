"""Tests for docfix_bot.scheduler."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from docfix_bot.models import make_broken_link, make_target, now_iso
from docfix_bot.scheduler import (
    generate_daily_report,
    run_daily_scan,
    should_continue,
)
from docfix_bot.state_store import StateStore


class TestShouldContinue:
    def test_under_limits(self, tmp_path: Path) -> None:
        state = StateStore(tmp_path / "state.json")
        config = {"max_prs_per_day": 10, "max_api_calls_per_hour": 500}
        assert should_continue(state, config) is True
        state.close()

    def test_daily_pr_limit(self, tmp_path: Path) -> None:
        state = StateStore(tmp_path / "state.json")
        config = {"max_prs_per_day": 0, "max_api_calls_per_hour": 500}
        assert should_continue(state, config) is False
        state.close()

    def test_hourly_api_limit(self, tmp_path: Path) -> None:
        state = StateStore(tmp_path / "state.json")
        config = {"max_prs_per_day": 10, "max_api_calls_per_hour": 0}
        assert should_continue(state, config) is False
        state.close()

    def test_default_limits(self, tmp_path: Path) -> None:
        state = StateStore(tmp_path / "state.json")
        config = {}
        assert should_continue(state, config) is True
        state.close()


class TestRunDailyScan:
    @patch("docfix_bot.scheduler.load_targets")
    def test_invalid_targets_returns_empty(self, mock_load: MagicMock, tmp_path: Path) -> None:
        mock_load.side_effect = ValueError("not found")
        state = StateStore(tmp_path / "state.json")
        config = {"targets_path": str(tmp_path / "targets.yaml")}
        result = run_daily_scan(config=config, state=state)
        assert result == []
        state.close()

    @patch("docfix_bot.scheduler.execute_fix_workflow")
    @patch("docfix_bot.scheduler.scan_repository")
    @patch("docfix_bot.scheduler.clone_repository")
    @patch("docfix_bot.scheduler.check_contributing_md")
    @patch("docfix_bot.scheduler.is_blocklisted")
    @patch("docfix_bot.scheduler.load_targets")
    @patch("docfix_bot.scheduler.prioritize_targets")
    def test_full_workflow(
        self,
        mock_prioritize: MagicMock,
        mock_load: MagicMock,
        mock_blocklist: MagicMock,
        mock_contributing: MagicMock,
        mock_clone: MagicMock,
        mock_scan: MagicMock,
        mock_execute: MagicMock,
        tmp_path: Path,
    ) -> None:
        target = make_target("org", "repo")
        mock_load.return_value = [target]
        mock_prioritize.return_value = [target]
        mock_blocklist.return_value = False
        mock_contributing.return_value = True
        mock_clone.return_value = tmp_path

        link = make_broken_link(
            "README.md",
            5,
            "https://old.com",
            404,
            suggested_fix="https://new.com",
            fix_confidence=0.9,
        )
        mock_scan.return_value = {
            "repository": target,
            "scan_time": now_iso(),
            "broken_links": [link],
            "error": None,
            "files_scanned": 1,
            "links_checked": 1,
        }
        mock_execute.return_value = {
            "repository": target,
            "branch_name": "fix/test",
            "pr_number": 42,
            "pr_url": "https://github.com/org/repo/pull/42",
            "status": "submitted",
            "broken_links_fixed": [link],
            "submitted_at": now_iso(),
        }

        state = StateStore(tmp_path / "state.json")
        config = {
            "targets_path": str(tmp_path / "targets.yaml"),
            "max_prs_per_day": 10,
            "max_api_calls_per_hour": 500,
        }
        result = run_daily_scan(config=config, state=state)
        assert len(result) == 1
        assert result[0]["pr_number"] == 42
        state.close()

    @patch("docfix_bot.scheduler.scan_repository")
    @patch("docfix_bot.scheduler.clone_repository")
    @patch("docfix_bot.scheduler.check_contributing_md")
    @patch("docfix_bot.scheduler.is_blocklisted")
    @patch("docfix_bot.scheduler.load_targets")
    @patch("docfix_bot.scheduler.prioritize_targets")
    def test_no_broken_links(
        self,
        mock_prioritize: MagicMock,
        mock_load: MagicMock,
        mock_blocklist: MagicMock,
        mock_contributing: MagicMock,
        mock_clone: MagicMock,
        mock_scan: MagicMock,
        tmp_path: Path,
    ) -> None:
        target = make_target("org", "repo")
        mock_load.return_value = [target]
        mock_prioritize.return_value = [target]
        mock_blocklist.return_value = False
        mock_contributing.return_value = True
        mock_clone.return_value = tmp_path
        mock_scan.return_value = {
            "repository": target,
            "scan_time": now_iso(),
            "broken_links": [],
            "error": None,
            "files_scanned": 1,
            "links_checked": 5,
        }

        state = StateStore(tmp_path / "state.json")
        config = {"targets_path": str(tmp_path / "targets.yaml")}
        result = run_daily_scan(config=config, state=state)
        assert result == []
        state.close()

    @patch("docfix_bot.scheduler.clone_repository")
    @patch("docfix_bot.scheduler.is_blocklisted")
    @patch("docfix_bot.scheduler.load_targets")
    @patch("docfix_bot.scheduler.prioritize_targets")
    def test_clone_failure(
        self,
        mock_prioritize: MagicMock,
        mock_load: MagicMock,
        mock_blocklist: MagicMock,
        mock_clone: MagicMock,
        tmp_path: Path,
    ) -> None:
        target = make_target("org", "repo")
        mock_load.return_value = [target]
        mock_prioritize.return_value = [target]
        mock_blocklist.return_value = False
        mock_clone.side_effect = RuntimeError("clone failed")

        state = StateStore(tmp_path / "state.json")
        config = {"targets_path": str(tmp_path / "targets.yaml")}
        result = run_daily_scan(config=config, state=state)
        assert result == []
        state.close()

    @patch("docfix_bot.scheduler.is_blocklisted")
    @patch("docfix_bot.scheduler.load_targets")
    @patch("docfix_bot.scheduler.prioritize_targets")
    def test_blocklisted_repo_skipped(
        self,
        mock_prioritize: MagicMock,
        mock_load: MagicMock,
        mock_blocklist: MagicMock,
        tmp_path: Path,
    ) -> None:
        target = make_target("org", "repo")
        mock_load.return_value = [target]
        mock_prioritize.return_value = [target]
        mock_blocklist.return_value = True

        state = StateStore(tmp_path / "state.json")
        config = {"targets_path": str(tmp_path / "targets.yaml")}
        result = run_daily_scan(config=config, state=state)
        assert result == []
        state.close()

    @patch("docfix_bot.scheduler.clone_repository")
    @patch("docfix_bot.scheduler.check_contributing_md")
    @patch("docfix_bot.scheduler.is_blocklisted")
    @patch("docfix_bot.scheduler.load_targets")
    @patch("docfix_bot.scheduler.prioritize_targets")
    def test_contributing_disallows_bots(
        self,
        mock_prioritize: MagicMock,
        mock_load: MagicMock,
        mock_blocklist: MagicMock,
        mock_contributing: MagicMock,
        mock_clone: MagicMock,
        tmp_path: Path,
    ) -> None:
        target = make_target("org", "repo")
        mock_load.return_value = [target]
        mock_prioritize.return_value = [target]
        mock_blocklist.return_value = False
        mock_contributing.return_value = False
        mock_clone.return_value = tmp_path

        state = StateStore(tmp_path / "state.json")
        config = {"targets_path": str(tmp_path / "targets.yaml")}
        result = run_daily_scan(config=config, state=state)
        assert result == []
        state.close()

    def test_defaults_used_when_none(self, tmp_path: Path) -> None:
        """When config/state are None, defaults are used."""
        # This test just verifies the function doesn't crash when
        # called with defaults (targets file won't exist)
        config = {
            "targets_path": str(tmp_path / "nonexistent.yaml"),
            "state_db_path": str(tmp_path / "state.json"),
        }
        result = run_daily_scan(config=config)
        assert result == []

    @patch("docfix_bot.scheduler.scan_repository")
    @patch("docfix_bot.scheduler.clone_repository")
    @patch("docfix_bot.scheduler.check_contributing_md")
    @patch("docfix_bot.scheduler.is_blocklisted")
    @patch("docfix_bot.scheduler.load_targets")
    @patch("docfix_bot.scheduler.prioritize_targets")
    def test_recently_scanned_skipped(
        self,
        mock_prioritize: MagicMock,
        mock_load: MagicMock,
        mock_blocklist: MagicMock,
        mock_contributing: MagicMock,
        mock_clone: MagicMock,
        mock_scan: MagicMock,
        tmp_path: Path,
    ) -> None:
        target = make_target("org", "repo")
        mock_load.return_value = [target]
        mock_prioritize.return_value = [target]
        mock_blocklist.return_value = False

        state = StateStore(tmp_path / "state.json")
        # Mark as recently scanned
        from datetime import datetime, timezone

        state.record_scan(target, datetime.now(timezone.utc).isoformat())

        config = {"targets_path": str(tmp_path / "targets.yaml")}
        result = run_daily_scan(config=config, state=state)
        assert result == []
        mock_clone.assert_not_called()
        state.close()

    @patch("docfix_bot.scheduler.scan_repository")
    @patch("docfix_bot.scheduler.clone_repository")
    @patch("docfix_bot.scheduler.check_contributing_md")
    @patch("docfix_bot.scheduler.is_blocklisted")
    @patch("docfix_bot.scheduler.load_targets")
    @patch("docfix_bot.scheduler.prioritize_targets")
    def test_all_links_already_fixed(
        self,
        mock_prioritize: MagicMock,
        mock_load: MagicMock,
        mock_blocklist: MagicMock,
        mock_contributing: MagicMock,
        mock_clone: MagicMock,
        mock_scan: MagicMock,
        tmp_path: Path,
    ) -> None:
        target = make_target("org", "repo")
        mock_load.return_value = [target]
        mock_prioritize.return_value = [target]
        mock_blocklist.return_value = False
        mock_contributing.return_value = True
        mock_clone.return_value = tmp_path

        link = make_broken_link(
            "README.md",
            5,
            "https://old.com",
            404,
            suggested_fix="https://new.com",
            fix_confidence=0.9,
        )
        mock_scan.return_value = {
            "repository": target,
            "scan_time": now_iso(),
            "broken_links": [link],
            "error": None,
            "files_scanned": 1,
            "links_checked": 1,
        }

        state = StateStore(tmp_path / "state.json")
        # Record that this link was already fixed
        from docfix_bot.models import PRSubmission

        submission: PRSubmission = {
            "repository": target,
            "branch_name": "fix/test",
            "pr_number": 1,
            "pr_url": "url",
            "status": "submitted",
            "broken_links_fixed": [link],
            "submitted_at": "2024-06-01T12:00:00+00:00",
        }
        state.record_pr_submission(submission)

        config = {"targets_path": str(tmp_path / "targets.yaml")}
        result = run_daily_scan(config=config, state=state)
        assert result == []
        state.close()

    @patch("docfix_bot.scheduler.scan_repository")
    @patch("docfix_bot.scheduler.clone_repository")
    @patch("docfix_bot.scheduler.check_contributing_md")
    @patch("docfix_bot.scheduler.is_blocklisted")
    @patch("docfix_bot.scheduler.load_targets")
    @patch("docfix_bot.scheduler.prioritize_targets")
    def test_no_fixable_links(
        self,
        mock_prioritize: MagicMock,
        mock_load: MagicMock,
        mock_blocklist: MagicMock,
        mock_contributing: MagicMock,
        mock_clone: MagicMock,
        mock_scan: MagicMock,
        tmp_path: Path,
    ) -> None:
        target = make_target("org", "repo")
        mock_load.return_value = [target]
        mock_prioritize.return_value = [target]
        mock_blocklist.return_value = False
        mock_contributing.return_value = True
        mock_clone.return_value = tmp_path

        # Broken link with no suggested fix
        link = make_broken_link("README.md", 5, "https://old.com", 404)
        mock_scan.return_value = {
            "repository": target,
            "scan_time": now_iso(),
            "broken_links": [link],
            "error": None,
            "files_scanned": 1,
            "links_checked": 1,
        }

        state = StateStore(tmp_path / "state.json")
        config = {"targets_path": str(tmp_path / "targets.yaml")}
        result = run_daily_scan(config=config, state=state)
        assert result == []
        state.close()

    @patch("docfix_bot.scheduler.should_continue")
    @patch("docfix_bot.scheduler.is_blocklisted")
    @patch("docfix_bot.scheduler.load_targets")
    @patch("docfix_bot.scheduler.prioritize_targets")
    def test_limit_reached_mid_loop(
        self,
        mock_prioritize: MagicMock,
        mock_load: MagicMock,
        mock_blocklist: MagicMock,
        mock_should_continue: MagicMock,
        tmp_path: Path,
    ) -> None:
        targets = [make_target("org", "repo1"), make_target("org", "repo2")]
        mock_load.return_value = targets
        mock_prioritize.return_value = targets
        mock_should_continue.return_value = False

        state = StateStore(tmp_path / "state.json")
        config = {"targets_path": str(tmp_path / "targets.yaml")}
        result = run_daily_scan(config=config, state=state)
        assert result == []
        # Should not have checked blocklist since should_continue returned False
        mock_blocklist.assert_not_called()
        state.close()

    @patch("docfix_bot.scheduler.load_targets")
    def test_default_config_and_state(self, mock_load: MagicMock, tmp_path: Path) -> None:
        """When config is None, get_default_config() is used."""
        mock_load.side_effect = ValueError("not found")
        # Pass None for config to trigger the default path
        result = run_daily_scan(config=None, state=StateStore(tmp_path / "state.json"))
        assert result == []


class TestGenerateDailyReport:
    def test_writes_report(self, tmp_path: Path) -> None:
        scan_results = [
            {
                "repository": make_target("org", "repo"),
                "scan_time": now_iso(),
                "broken_links": [
                    make_broken_link("README.md", 1, "https://old.com", 404),
                ],
                "error": None,
                "files_scanned": 1,
                "links_checked": 1,
            }
        ]
        submissions = []
        output = tmp_path / "report.json"
        generate_daily_report(scan_results, submissions, output)
        assert output.exists()
        data = json.loads(output.read_text())
        assert data["repos_scanned"] == 1
        assert data["prs_submitted"] == 0
        assert data["total_broken_links"] == 1

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        output = tmp_path / "nested" / "dir" / "report.json"
        generate_daily_report([], [], output)
        assert output.exists()

    def test_empty_results(self, tmp_path: Path) -> None:
        output = tmp_path / "report.json"
        generate_daily_report([], [], output)
        data = json.loads(output.read_text())
        assert data["repos_scanned"] == 0
        assert data["prs_submitted"] == 0
        assert data["total_broken_links"] == 0
