"""Tests for docfix_bot.state_store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from docfix_bot.models import PRSubmission, make_broken_link, make_target
from docfix_bot.state_store import StateStore


class TestStateStoreInit:
    def test_creates_db(self, tmp_path: Path) -> None:
        db_path = tmp_path / "state.json"
        store = StateStore(db_path)
        assert db_path.exists()
        store.close()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nested" / "dir" / "state.json"
        store = StateStore(db_path)
        assert db_path.exists()
        store.close()


class TestRecordPrSubmission:
    def test_records_and_persists(self, tmp_path: Path) -> None:
        db_path = tmp_path / "state.json"
        store = StateStore(db_path)
        target = make_target("org", "repo")
        link = make_broken_link("README.md", 1, "https://old.com", 404)
        submission: PRSubmission = {
            "repository": target,
            "branch_name": "fix/test",
            "pr_number": 42,
            "pr_url": "https://github.com/org/repo/pull/42",
            "status": "submitted",
            "broken_links_fixed": [link],
            "submitted_at": "2024-06-01T12:00:00+00:00",
        }
        store.record_pr_submission(submission)
        # Verify the link is now tracked
        assert store.was_link_already_fixed(target, "https://old.com") is True
        store.close()


class TestWasLinkAlreadyFixed:
    def test_not_fixed(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "state.json")
        target = make_target("org", "repo")
        assert store.was_link_already_fixed(target, "https://new.com") is False
        store.close()

    def test_different_repo(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "state.json")
        target1 = make_target("org", "repo1")
        target2 = make_target("org", "repo2")
        link = make_broken_link("README.md", 1, "https://old.com", 404)
        submission: PRSubmission = {
            "repository": target1,
            "branch_name": "fix/test",
            "pr_number": 1,
            "pr_url": "url",
            "status": "submitted",
            "broken_links_fixed": [link],
            "submitted_at": "2024-06-01T12:00:00+00:00",
        }
        store.record_pr_submission(submission)
        assert store.was_link_already_fixed(target2, "https://old.com") is False
        store.close()


class TestDailyPrCount:
    def test_zero_when_empty(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "state.json")
        assert store.get_daily_pr_count() == 0
        store.close()

    def test_counts_today(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "state.json")
        target = make_target("org", "repo")
        link = make_broken_link("README.md", 1, "https://old.com", 404)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        submission: PRSubmission = {
            "repository": target,
            "branch_name": "fix/test",
            "pr_number": 1,
            "pr_url": "url",
            "status": "submitted",
            "broken_links_fixed": [link],
            "submitted_at": f"{today}T12:00:00+00:00",
        }
        store.record_pr_submission(submission)
        assert store.get_daily_pr_count() == 1
        store.close()

    def test_ignores_yesterday(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "state.json")
        target = make_target("org", "repo")
        link = make_broken_link("README.md", 1, "https://old.com", 404)
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        submission: PRSubmission = {
            "repository": target,
            "branch_name": "fix/test",
            "pr_number": 1,
            "pr_url": "url",
            "status": "submitted",
            "broken_links_fixed": [link],
            "submitted_at": f"{yesterday}T12:00:00+00:00",
        }
        store.record_pr_submission(submission)
        assert store.get_daily_pr_count() == 0
        store.close()


class TestHourlyApiCount:
    def test_zero_when_empty(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "state.json")
        assert store.get_hourly_api_count() == 0
        store.close()

    def test_increments(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "state.json")
        store.increment_api_count()
        store.increment_api_count()
        assert store.get_hourly_api_count() == 2
        store.close()


class TestRecordScan:
    def test_records_scan(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "state.json")
        target = make_target("org", "repo")
        store.record_scan(target, datetime.now(timezone.utc).isoformat())
        assert store.was_recently_scanned(target) is True
        store.close()


class TestWasRecentlyScanned:
    def test_not_scanned(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "state.json")
        target = make_target("org", "repo")
        assert store.was_recently_scanned(target) is False
        store.close()

    def test_old_scan(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "state.json")
        target = make_target("org", "repo")
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        store.record_scan(target, old_time)
        assert store.was_recently_scanned(target) is False
        store.close()

    def test_recent_scan(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "state.json")
        target = make_target("org", "repo")
        recent_time = datetime.now(timezone.utc).isoformat()
        store.record_scan(target, recent_time)
        assert store.was_recently_scanned(target, hours=24) is True
        store.close()

    def test_custom_hours(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "state.json")
        target = make_target("org", "repo")
        two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        store.record_scan(target, two_hours_ago)
        assert store.was_recently_scanned(target, hours=1) is False
        assert store.was_recently_scanned(target, hours=3) is True
        store.close()
