"""Stream a bulk-scan run's progress to stdout as a single status line per
tick.

Out-of-process: polls the DB; never touches the running scan. Use for
inspecting non-active runs (post-mortem) or alongside a stage that emits
to a different log destination. The in-process emitter inside
``runner.run_full()`` is the primary visibility surface during a live
scan (PR #360).

Shape per tick matches ``tools/finish_stage*.py`` and the in-process
emitter (PR #271 schema) -- both delegate to
``gh_link_auditor.bulk_scan.progress.render``. The two code paths are
guaranteed not to drift because they call the same function (#368).

Usage::

    poetry run python tools/watch_bulk_scan.py [RUN_ID]
    poetry run python tools/watch_bulk_scan.py --interval 15

If RUN_ID is omitted, watches the most-recent run.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gh_link_auditor.bulk_scan import progress, storage  # noqa: E402
from gh_link_auditor.unified_db import DEFAULT_DB_PATH, UnifiedDatabase  # noqa: E402


def _resolve_run_id(db: UnifiedDatabase, requested: str | None) -> str | None:
    if requested:
        return requested
    runs = storage.list_runs(db, limit=1)
    return runs[0]["run_id"] if runs else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("run_id", nargs="?", default=None)
    parser.add_argument("--interval", type=int, default=30, help="poll interval seconds (default 30)")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()

    started_mono = time.monotonic()
    # Three rolling windows matching the in-process StatusEmitter:
    # stage1 (repo-processed), findings (total URLs), stage3 (processed URLs).
    stage1_window: deque = deque(maxlen=10)
    findings_window: deque = deque(maxlen=10)
    stage3_window: deque = deque(maxlen=10)

    while True:
        try:
            with UnifiedDatabase(args.db_path) as db:
                run_id = _resolve_run_id(db, args.run_id)
                if not run_id:
                    print("no runs found", flush=True)
                    return 1
                snap = progress.snapshot(db, run_id)
        except Exception as exc:  # noqa: BLE001
            print(f"poll error: {exc}", flush=True)
            time.sleep(args.interval)
            continue

        if not snap:
            print(f"run {run_id} not found", flush=True)
            return 1

        counts = snap["counts"]
        now_mono = time.monotonic()
        stage1_window.append((now_mono, counts.get("inventoried", 0) + counts.get("error", 0)))
        findings_window.append((now_mono, snap["total_findings"]))
        pending3 = snap.get("inv_buckets", {}).get("pending", 0)
        stage3_window.append((now_mono, snap["total_findings"] - pending3))

        line = progress.render(snap, stage1_window, findings_window, stage3_window, started_mono)
        print(line, flush=True)

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
