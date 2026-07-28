"""Tests for bulk-scan run reconciliation (#426)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from gh_link_auditor.bulk_scan import storage
from gh_link_auditor.unified_db import UnifiedDatabase

# Injected everywhere — no wall-clock in assertions (lesson #433).
NOW = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    with UnifiedDatabase(str(tmp_path / "t.db")) as udb:
        yield udb


def _insert_run(db, run_id: str, status: str, started_hours_ago: float) -> None:
    started = (NOW - timedelta(hours=started_hours_ago)).isoformat()
    db._conn.execute(
        "INSERT INTO bulk_scan_runs (run_id, started_at, status, target_repo_count) VALUES (?,?,?,?)",
        (run_id, started, status, 100),
    )
    db._conn.commit()


def _lock_run(db, run_id: str) -> None:
    db._conn.execute(
        "INSERT INTO bulk_scan_locks (run_id, host, pid, started_at) VALUES (?,?,?,?)",
        (run_id, "testhost", 1234, NOW.isoformat()),
    )
    db._conn.commit()


class TestFindAbandonedRuns:
    def test_old_nonterminal_run_found(self, db):
        _insert_run(db, "r-old", "checking", started_hours_ago=48)
        found = storage.find_abandoned_runs(db, older_than_hours=24, now=NOW)
        assert [r["run_id"] for r in found] == ["r-old"]

    def test_terminal_runs_not_found(self, db):
        for i, status in enumerate(storage.TERMINAL_RUN_STATUSES):
            _insert_run(db, f"r-{status}", status, started_hours_ago=48 + i)
        assert storage.find_abandoned_runs(db, older_than_hours=24, now=NOW) == []

    def test_young_nonterminal_run_not_found(self, db):
        _insert_run(db, "r-young", "inventorying", started_hours_ago=1)
        assert storage.find_abandoned_runs(db, older_than_hours=24, now=NOW) == []

    def test_locked_run_not_found(self, db):
        _insert_run(db, "r-live", "investigating", started_hours_ago=100)
        _lock_run(db, "r-live")
        assert storage.find_abandoned_runs(db, older_than_hours=24, now=NOW) == []

    def test_threshold_boundary_respected(self, db):
        _insert_run(db, "r-23h", "checking", started_hours_ago=23)
        _insert_run(db, "r-25h", "checking", started_hours_ago=25)
        found = storage.find_abandoned_runs(db, older_than_hours=24, now=NOW)
        assert [r["run_id"] for r in found] == ["r-25h"]


class TestReconcileAbandonedRuns:
    def test_flips_to_aborted_with_error_and_completed_at(self, db):
        _insert_run(db, "r-old", "checking", started_hours_ago=48)
        flipped = storage.reconcile_abandoned_runs(db, older_than_hours=24, now=NOW)
        assert flipped == ["r-old"]
        run = storage.get_run(db, "r-old")
        assert run["status"] == "aborted"
        assert run["completed_at"] is not None
        assert "reconciled: abandoned" in run["error"]
        assert "'checking'" in run["error"]

    def test_idempotent_second_call_returns_empty(self, db):
        _insert_run(db, "r-old", "checking", started_hours_ago=48)
        assert storage.reconcile_abandoned_runs(db, older_than_hours=24, now=NOW) == ["r-old"]
        assert storage.reconcile_abandoned_runs(db, older_than_hours=24, now=NOW) == []

    def test_leaves_live_and_terminal_runs_untouched(self, db):
        _insert_run(db, "r-done", "done", started_hours_ago=100)
        _insert_run(db, "r-live", "checking", started_hours_ago=100)
        _lock_run(db, "r-live")
        _insert_run(db, "r-dead", "checking", started_hours_ago=100)
        before_done = storage.get_run(db, "r-done")
        before_live = storage.get_run(db, "r-live")
        flipped = storage.reconcile_abandoned_runs(db, older_than_hours=24, now=NOW)
        assert flipped == ["r-dead"]
        assert storage.get_run(db, "r-done") == before_done
        assert storage.get_run(db, "r-live") == before_live
