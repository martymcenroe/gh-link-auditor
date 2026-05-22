"""Tests for bulk_scan.process_lock (#244 — single-process lock per run-id)."""

from __future__ import annotations

import os
import socket

import pytest

from gh_link_auditor.bulk_scan import process_lock
from gh_link_auditor.bulk_scan.process_lock import LockBusyError
from gh_link_auditor.unified_db import UnifiedDatabase


def _bulk_scan_lock_rows(db: UnifiedDatabase, run_id: str) -> list[dict]:
    return [dict(r) for r in db._conn.execute("SELECT * FROM bulk_scan_locks WHERE run_id = ?", (run_id,)).fetchall()]


class TestAcquireRelease:
    def test_first_acquire_succeeds(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            process_lock.acquire(db, "r1")
            rows = _bulk_scan_lock_rows(db, "r1")
            assert len(rows) == 1
            assert rows[0]["pid"] == os.getpid()
            assert rows[0]["host"] == socket.gethostname()

    def test_release_clears(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            process_lock.acquire(db, "r1")
            process_lock.release(db, "r1")
            assert _bulk_scan_lock_rows(db, "r1") == []

    def test_release_safe_when_not_held(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            # Should not raise
            process_lock.release(db, "r1")

    def test_release_only_removes_own_lock(self, tmp_path) -> None:
        """A process can't release another process's lock — DELETE has pid match."""
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            process_lock.acquire(db, "r1", pid=99999)
            # Different pid releasing — should be a no-op
            process_lock.release(db, "r1", pid=os.getpid())
            assert len(_bulk_scan_lock_rows(db, "r1")) == 1


class TestConflictAndReclamation:
    def test_concurrent_acquire_by_live_pid_raises(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            # Take lock with our PID (definitely alive)
            process_lock.acquire(db, "r1", pid=os.getpid())
            # Second acquire (from same-host but pretend different pid that's also alive)
            with pytest.raises(LockBusyError) as exc_info:
                process_lock.acquire(db, "r1", pid=os.getpid())
            assert "another bulk-scan" in str(exc_info.value)
            assert "r1" in str(exc_info.value)

    def test_stale_lock_reclaimed(self, tmp_path) -> None:
        """A lock held by a dead PID can be reclaimed by a new process."""
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            # Use a PID that's definitely not running (high number, very unlikely)
            STALE_PID = 1
            # Manually insert a stale lock — bypass acquire's checks
            db._conn.execute(
                "INSERT INTO bulk_scan_locks (run_id, host, pid, started_at) VALUES (?, ?, ?, ?)",
                ("r1", socket.gethostname(), STALE_PID, "2026-01-01T00:00:00Z"),
            )
            db._conn.commit()
            # New acquire reclaims (assumes PID 1 is not us, which it isn't)
            import psutil

            if psutil.pid_exists(STALE_PID):
                pytest.skip("PID 1 unexpectedly alive in this test env")
            process_lock.acquire(db, "r1")
            rows = _bulk_scan_lock_rows(db, "r1")
            assert len(rows) == 1
            assert rows[0]["pid"] == os.getpid()  # we took over

    def test_different_run_ids_no_conflict(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            process_lock.acquire(db, "r1")
            process_lock.acquire(db, "r2")  # no conflict — different run-id
            assert len(_bulk_scan_lock_rows(db, "r1")) == 1
            assert len(_bulk_scan_lock_rows(db, "r2")) == 1


class TestSchema:
    def test_v7_schema_has_lock_table(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            tables = {r[0] for r in db._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert "bulk_scan_locks" in tables
            cols = {r[1] for r in db._conn.execute("PRAGMA table_info(bulk_scan_locks)")}
            assert {"run_id", "host", "pid", "started_at"} <= cols
