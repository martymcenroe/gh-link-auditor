"""Stage-aware progress rendering for the bulk-scan pipeline.

A single source of truth for the status line emitted by:
- runner.run_full() -- in-process daemon thread, one line per 30s, INFO logger
- tools/watch_bulk_scan.py -- out-of-process poller, prints to stdout

Status line shape matches tools/finish_stage{1,2,3}.py (PR #271):

    [HH:MM:SS] stage<N> processed/total (pct%) ... rate=R/min (5m: r/min) ETA=T

Per-stage detail:
- stage1 (selecting/inventorying): inventoried/target with findings count
- stage2 (checking): findings probed
- stage3 (investigating): GROUP BY investigation_state buckets,
  yield%, candidates inserted
- stage4/5 (scoring/done): scoring snapshot

All queries are read-only against bulk_scan_findings / bulk_scan_runs /
bulk_scan_repos -- safe to run alongside an active scan.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any

from gh_link_auditor.bulk_scan import scoring, storage
from gh_link_auditor.unified_db import UnifiedDatabase

logger = logging.getLogger(__name__)

# Map bulk_scan_runs.status -> stage number for the prefix
STAGE_MAP = {
    "selecting": 1,
    "inventorying": 1,
    "checking": 2,
    "investigating": 3,
    "scoring": 4,
    "done": 5,
    "quality_aborted": 5,
    "aborted": 5,
}

DEFAULT_INTERVAL_S = 30.0


def investigation_buckets(db: UnifiedDatabase, run_id: str) -> dict[str, int]:
    """Group bulk_scan_findings by investigation_state for the run."""
    rows = db._conn.execute(
        "SELECT investigation_state, COUNT(*) AS n FROM bulk_scan_findings "
        "WHERE run_id = ? GROUP BY investigation_state",
        (run_id,),
    ).fetchall()
    return {r["investigation_state"]: r["n"] for r in rows}


def snapshot(db: UnifiedDatabase, run_id: str) -> dict[str, Any]:
    """Read-only DB snapshot used by both in-process and out-of-process emitters."""
    run = storage.get_run(db, run_id)
    if run is None:
        return {}
    counts = storage.get_repo_count_by_status(db, run_id)
    total = storage.count_findings(db, run_id)
    surfaced = storage.count_findings(db, run_id, surfaced=True)
    median = scoring.quality_sample_median(db, run_id)
    inv_buckets = investigation_buckets(db, run_id)
    return {
        "status": run["status"],
        "counts": counts,
        "total_findings": total,
        "surfaced": surfaced,
        "median": median,
        "target": run.get("target_repo_count") or 0,
        "inv_buckets": inv_buckets,
    }


def _eta_str(remaining: int, rate_per_min: float) -> str:
    if rate_per_min <= 0:
        return "?"
    m = remaining / rate_per_min
    return f"{m:.0f}m" if m < 60 else f"{m / 60:.1f}h"


def _rate(window: deque) -> float:
    """Per-minute rate over the rolling window."""
    if len(window) < 2:
        return 0.0
    ts0, v0 = window[0]
    ts1, v1 = window[-1]
    dt = ts1 - ts0
    if dt <= 0:
        return 0.0
    return (v1 - v0) / (dt / 60.0)


def render(
    snap: dict[str, Any],
    stage1_window: deque,
    findings_window: deque,
    stage3_window: deque,
    started_mono: float,
) -> str:
    """Return a single-line status string for the current stage."""
    now = datetime.now().strftime("%H:%M:%S")
    status = snap["status"]
    stage = STAGE_MAP.get(status, 0)
    counts = snap["counts"]
    target = snap["target"]
    inv_repos = counts.get("inventoried", 0)
    pend_repos = counts.get("pending", 0)
    err_repos = counts.get("error", 0)
    findings = snap["total_findings"]
    surfaced = snap["surfaced"]
    buckets = snap.get("inv_buckets", {})

    if stage == 1:
        processed = inv_repos + err_repos
        pct = (100.0 * processed / target) if target else 0.0
        elapsed_min = (time.monotonic() - started_mono) / 60.0
        overall = (processed / elapsed_min) if elapsed_min > 0.1 else 0.0
        recent = _rate(stage1_window)
        findings_recent = _rate(findings_window)
        remaining = max(target - processed, 0)
        eta = _eta_str(remaining, recent if recent > 0 else overall)
        return (
            f"[{now}] stage1 {processed:,}/{target:,} ({pct:.1f}%) "
            f"inventoried={inv_repos:,} pending={pend_repos:,} err={err_repos:,} "
            f"findings={findings:,} (5m: {findings_recent:+.0f}/min) "
            f"rate={overall:.1f}/min (5m: {recent:.1f}/min) ETA={eta}"
        )
    if stage == 2:
        findings_recent = _rate(findings_window)
        return (
            f"[{now}] stage2 status=checking findings={findings:,} "
            f"surfaced={surfaced:,} (5m: {findings_recent:+.0f}/min)"
        )
    if stage == 3:
        pending = buckets.get("pending", 0)
        processed = findings - pending
        pct = (100.0 * processed / findings) if findings else 0.0
        inv_with = buckets.get("investigated_with_candidate", 0)
        inv_no = buckets.get("investigated_no_candidate", 0)
        derived = buckets.get("derived_candidate", 0)
        real_invs = inv_with + inv_no
        yield_str = f"yield={100.0 * inv_with / real_invs:.1f}%" if real_invs else "yield=n/a"
        skipped_total = (
            buckets.get("skipped_alive", 0) + buckets.get("skipped_language", 0) + buckets.get("skipped_blocklist", 0)
        )
        rate = _rate(stage3_window)
        eta = _eta_str(pending, rate)
        return (
            f"[{now}] stage3 {processed:,}/{findings:,} ({pct:.1f}%) "
            f"skipped={skipped_total:,} investigated={real_invs:,} {yield_str} "
            f"cands+={derived:,} (5m: {rate:+.0f}/min) ETA={eta}"
        )
    median_str = f" sample_median={snap['median']:.2f}" if snap.get("median") else ""
    if stage == 4:
        return f"[{now}] stage4 scoring surfaced={surfaced:,}{median_str}"
    if stage == 5:
        return f"[{now}] stage5 status={status} surfaced={surfaced:,}/{findings:,}{median_str}"
    return f"[{now}] status={status} (no progress data -- stage unknown)"


class StatusEmitter:
    """Background daemon thread that polls the DB and emits a status line
    every ``interval_s`` seconds via the module logger.

    Started by runner.run_full() at the top, stopped in the finally block.
    Re-entrant safe: stop() is idempotent.

    The daemon thread opens its OWN ``UnifiedDatabase`` (#390 / #F3):
    sqlite3 connections have ``check_same_thread=True`` by default, so
    sharing the caller's connection would raise ``ProgrammingError`` on
    every poll tick and silently lose every status line.
    """

    def __init__(
        self,
        db: UnifiedDatabase,
        run_id: str,
        interval_s: float = DEFAULT_INTERVAL_S,
        log: logging.Logger | None = None,
        *,
        db_path: str | None = None,
    ) -> None:
        # Resolve the DB path now so the daemon thread can open its own
        # connection. Fall back to the supplied db's ``_db_path`` for
        # backwards compatibility with callers that don't pass db_path.
        resolved_db_path = db_path or getattr(db, "_db_path", None)
        if not resolved_db_path:
            raise ValueError(
                "StatusEmitter needs a db_path -- pass db_path explicitly or "
                "ensure the supplied UnifiedDatabase exposes _db_path."
            )
        self._db_path: str = str(resolved_db_path)
        # _db is retained for backwards-compat in case any external caller
        # touches it, but is NOT used from the daemon thread.
        self._db = db
        self._run_id = run_id
        self._interval_s = interval_s
        self._log = log or logger
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stage1_window: deque = deque(maxlen=10)
        self._findings_window: deque = deque(maxlen=10)
        self._stage3_window: deque = deque(maxlen=10)
        self._started_mono = time.monotonic()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name=f"status-emitter-{self._run_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self._interval_s + 5.0)

    def _run(self) -> None:
        # Open a thread-local UnifiedDatabase. The caller's db._conn cannot
        # be used from this thread (sqlite3 ProgrammingError); see #390.
        thread_db = UnifiedDatabase(self._db_path)
        try:
            # First emission shortly after start so the operator sees the
            # line before having to wait a full interval.
            first_wait = min(2.0, self._interval_s)
            if self._stop.wait(first_wait):
                return
            while not self._stop.is_set():
                try:
                    snap = snapshot(thread_db, self._run_id)
                    if snap:
                        now_mono = time.monotonic()
                        counts = snap["counts"]
                        self._stage1_window.append((now_mono, counts.get("inventoried", 0) + counts.get("error", 0)))
                        self._findings_window.append((now_mono, snap["total_findings"]))
                        pending3 = snap.get("inv_buckets", {}).get("pending", 0)
                        self._stage3_window.append((now_mono, snap["total_findings"] - pending3))
                        line = render(
                            snap,
                            self._stage1_window,
                            self._findings_window,
                            self._stage3_window,
                            self._started_mono,
                        )
                        self._log.info(line)
                except Exception as exc:  # noqa: BLE001
                    self._log.warning("status emitter poll error: %s", exc)
                if self._stop.wait(self._interval_s):
                    return
        finally:
            try:
                thread_db.close()
            except Exception:  # noqa: BLE001
                pass
