"""Poll a running bulk-scan and print progress to the console.

Workaround for the CLI's missing logging output (fix landing as a PR).
Until that ships, run this in a second terminal alongside the scan and
you'll see the repo-count incrementing, findings count incrementing, and
a rough rate + ETA.

Usage::

    poetry run python tools/watch_bulk_scan.py [RUN_ID]
    poetry run python tools/watch_bulk_scan.py --interval 15

If RUN_ID is omitted, watches the most-recent run.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gh_link_auditor.bulk_scan import scoring, storage  # noqa: E402
from gh_link_auditor.unified_db import DEFAULT_DB_PATH, UnifiedDatabase  # noqa: E402


def _resolve_run_id(db: UnifiedDatabase, requested: str | None) -> str | None:
    if requested:
        return requested
    runs = storage.list_runs(db, limit=1)
    return runs[0]["run_id"] if runs else None


def _snapshot(db: UnifiedDatabase, run_id: str) -> dict:
    run = storage.get_run(db, run_id)
    if run is None:
        return {}
    counts = storage.get_repo_count_by_status(db, run_id)
    total = storage.count_findings(db, run_id)
    surfaced = storage.count_findings(db, run_id, surfaced=True)
    median = scoring.quality_sample_median(db, run_id)
    return {
        "status": run["status"],
        "counts": counts,
        "total": total,
        "surfaced": surfaced,
        "median": median,
        "target": run.get("target_repo_count") or 0,
    }


def _format_delta(curr: int, prev: int | None) -> str:
    if prev is None:
        return ""
    d = curr - prev
    return f" (+{d})" if d > 0 else " (=)" if d == 0 else f" ({d})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", nargs="?", default=None)
    parser.add_argument("--interval", type=int, default=30, help="poll interval seconds (default 30)")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()

    started_wall: float | None = None
    first_inv: int | None = None
    prev_inv: int | None = None
    prev_total: int | None = None

    while True:
        try:
            with UnifiedDatabase(args.db_path) as db:
                run_id = _resolve_run_id(db, args.run_id)
                if not run_id:
                    print("no runs found", flush=True)
                    return 1
                snap = _snapshot(db, run_id)
        except Exception as exc:  # noqa: BLE001
            print(f"poll error: {exc}", flush=True)
            time.sleep(args.interval)
            continue

        if not snap:
            print(f"run {run_id} not found", flush=True)
            return 1

        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        counts = snap["counts"]
        inv = counts.get("inventoried", 0)
        pend = counts.get("pending", 0)
        err = counts.get("error", 0)
        if started_wall is None:
            started_wall = time.time()
            first_inv = inv
        elapsed_min = (time.time() - started_wall) / 60
        gained = inv - (first_inv or 0)
        rate = (gained / elapsed_min) if elapsed_min > 0.1 else 0.0
        remaining = max(snap["target"] - inv, 0)
        eta_min = (remaining / rate) if rate > 0 else None
        eta_str = f"ETA ~{eta_min:.0f}m" if eta_min is not None else "ETA n/a"

        print(
            f"[{now}] {run_id} status={snap['status']:13s} "
            f"inventoried={inv}/{snap['target']}{_format_delta(inv, prev_inv)} "
            f"pending={pend} err={err} "
            f"findings={snap['total']}{_format_delta(snap['total'], prev_total)} "
            f"rate={rate:.1f}/min {eta_str}",
            flush=True,
        )

        prev_inv = inv
        prev_total = snap["total"]

        if snap["status"] in ("done", "quality_aborted", "aborted"):
            print(f"\nrun finished with status: {snap['status']}", flush=True)
            return 0

        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\ninterrupted (the scan keeps running; just stopping the watcher)", flush=True)
            return 0


if __name__ == "__main__":
    sys.exit(main())
