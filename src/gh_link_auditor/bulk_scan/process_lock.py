"""Single-process lock per (run_id, host) — prevents two bulk-scans racing the same DB (#244).

Two processes against the same run-id both call run_investigation; each tries to
delete-then-insert the same finding rows; neither makes progress; both can destroy
Stage 1's hours of doc-fetch work. We need to make that scenario impossible.

The lock lives in ``bulk_scan_locks`` (created by schema v7). On startup, take the
lock; if held by a still-alive process on this host, exit. Stale locks
(PID not alive) are reclaimed automatically.
"""

from __future__ import annotations

import logging
import os
import socket
import sqlite3
from datetime import datetime, timezone

import psutil

from gh_link_auditor.unified_db import UnifiedDatabase

logger = logging.getLogger(__name__)


class LockBusyError(RuntimeError):
    """Another live process holds the lock for this run_id on this host."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_pid_alive(pid: int) -> bool:
    """Cross-platform check that ``pid`` corresponds to a running process."""
    try:
        return psutil.pid_exists(pid)
    except Exception:
        return False


def acquire(db: UnifiedDatabase, run_id: str, *, pid: int | None = None, host: str | None = None) -> None:
    """Acquire the lock for (run_id, host). Raise LockBusyError if held by another live PID.

    Stale locks (PID not alive) are reclaimed automatically.
    """
    pid = pid if pid is not None else os.getpid()
    host = host if host is not None else socket.gethostname()
    try:
        db._conn.execute(
            "INSERT INTO bulk_scan_locks (run_id, host, pid, started_at) VALUES (?, ?, ?, ?)",
            (run_id, host, pid, _now_iso()),
        )
        db._conn.commit()
        logger.info("acquired bulk-scan lock: run_id=%s pid=%s host=%s", run_id, pid, host)
        return
    except sqlite3.IntegrityError:
        # Lock exists; check whether the holder is still alive.
        existing = db._conn.execute(
            "SELECT pid FROM bulk_scan_locks WHERE run_id = ? AND host = ?",
            (run_id, host),
        ).fetchone()
        if existing is None:
            # Race: row got deleted between our INSERT failure and the SELECT. Retry once.
            db._conn.execute(
                "INSERT INTO bulk_scan_locks (run_id, host, pid, started_at) VALUES (?, ?, ?, ?)",
                (run_id, host, pid, _now_iso()),
            )
            db._conn.commit()
            return
        existing_pid = existing["pid"]
        if _is_pid_alive(existing_pid):
            raise LockBusyError(
                f"another bulk-scan process is running for run-id {run_id!r} "
                f"(PID {existing_pid} on host {host!r}); refusing to race"
            )
        # Stale lock — reclaim.
        logger.warning(
            "reclaiming stale bulk-scan lock: run_id=%s prior_pid=%s (not alive)",
            run_id,
            existing_pid,
        )
        db._conn.execute(
            "UPDATE bulk_scan_locks SET pid = ?, started_at = ? WHERE run_id = ? AND host = ?",
            (pid, _now_iso(), run_id, host),
        )
        db._conn.commit()


def release(db: UnifiedDatabase, run_id: str, *, pid: int | None = None, host: str | None = None) -> None:
    """Release the lock if we hold it. No-op if we don't (stale-release safe)."""
    pid = pid if pid is not None else os.getpid()
    host = host if host is not None else socket.gethostname()
    db._conn.execute(
        "DELETE FROM bulk_scan_locks WHERE run_id = ? AND host = ? AND pid = ?",
        (run_id, host, pid),
    )
    db._conn.commit()
    logger.debug("released bulk-scan lock: run_id=%s pid=%s host=%s", run_id, pid, host)
