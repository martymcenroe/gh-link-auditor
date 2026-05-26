"""Stream a bulk-scan run's progress to stdout as a single status line per
tick, matching the shape of tools/finish_stage{1,2,3}.py.

Out-of-process: polls the DB; never touches the running scan. Run in a
second terminal alongside `ghla bulk-scan start`.

Shape per tick (matches PR #271 / finish_stage*.py render_line):

    [HH:MM:SS] stage<N> processed/total (pct%) bucket=<count> ...
        findings+=<N> rate=<r>/min (5m: <r>/min) ETA=<T>

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
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gh_link_auditor.bulk_scan import scoring, storage  # noqa: E402
from gh_link_auditor.unified_db import DEFAULT_DB_PATH, UnifiedDatabase  # noqa: E402

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


def _investigation_buckets(db: UnifiedDatabase, run_id: str) -> dict[str, int]:
    """Group bulk_scan_findings by investigation_state for the run.

    Mirrors finish_stage3.py's Stats buckets:
    - pending: stage-2 left these for stage 3
    - skipped_alive / skipped_language / skipped_blocklist: outside stage 3 work
    - investigated_no_candidate / investigated_with_candidate: real stage-3 investigations
    - derived_candidate: an inserted candidate row (cands+)
    - dropped_unsafe_url: filtered out post-investigation
    """
    rows = db._conn.execute(
        "SELECT investigation_state, COUNT(*) AS n FROM bulk_scan_findings "
        "WHERE run_id = ? GROUP BY investigation_state",
        (run_id,),
    ).fetchall()
    return {r["investigation_state"]: r["n"] for r in rows}


def _snapshot(db: UnifiedDatabase, run_id: str) -> dict:
    run = storage.get_run(db, run_id)
    if run is None:
        return {}
    counts = storage.get_repo_count_by_status(db, run_id)
    total = storage.count_findings(db, run_id)
    surfaced = storage.count_findings(db, run_id, surfaced=True)
    median = scoring.quality_sample_median(db, run_id)
    inv_buckets = _investigation_buckets(db, run_id)
    return {
        "status": run["status"],
        "counts": counts,
        "total_findings": total,
        "surfaced": surfaced,
        "median": median,
        "target": run.get("target_repo_count") or 0,
        "inv_buckets": inv_buckets,
    }


def _resolve_run_id(db: UnifiedDatabase, requested: str | None) -> str | None:
    if requested:
        return requested
    runs = storage.list_runs(db, limit=1)
    return runs[0]["run_id"] if runs else None


def _eta_str(remaining: int, rate_per_min: float) -> str:
    if rate_per_min <= 0:
        return "?"
    m = remaining / rate_per_min
    return f"{m:.0f}m" if m < 60 else f"{m / 60:.1f}h"


def _five_min_rate(window: deque) -> float:
    """Rate per minute over the rolling window. Returns 0 if insufficient samples."""
    if len(window) < 2:
        return 0.0
    ts0, v0 = window[0]
    ts1, v1 = window[-1]
    dt = ts1 - ts0
    if dt <= 0:
        return 0.0
    return (v1 - v0) / (dt / 60.0)


def _render(snap: dict, run_id: str, mono_window: deque, findings_window: deque, started_mono: float) -> str:
    now = datetime.now().strftime("%H:%M:%S")
    status = snap["status"]
    stage = STAGE_MAP.get(status, 0)
    counts = snap["counts"]
    target = snap["target"]
    inv = counts.get("inventoried", 0)
    pend = counts.get("pending", 0)
    err = counts.get("error", 0)
    findings = snap["total_findings"]
    surfaced = snap["surfaced"]

    processed = inv + err
    pct = (100.0 * processed / target) if target else 0.0

    elapsed_min = (time.monotonic() - started_mono) / 60.0
    overall_rate = (processed / elapsed_min) if elapsed_min > 0.1 else 0.0
    recent_rate = _five_min_rate(mono_window)
    findings_rate = _five_min_rate(findings_window)
    remaining = max(target - processed, 0)
    eta = _eta_str(remaining, recent_rate if recent_rate > 0 else overall_rate)

    median_str = f" sample_median={snap['median']:.2f}" if snap.get("median") else ""

    if stage == 1:
        # Stage 1 -- selection + inventory. Per-repo progress is the headline.
        return (
            f"[{now}] stage1 {processed:,}/{target:,} ({pct:.1f}%) "
            f"inventoried={inv:,} pending={pend:,} err={err:,} "
            f"findings={findings:,} (5m: {findings_rate:+.0f}/min) "
            f"rate={overall_rate:.1f}/min (5m: {recent_rate:.1f}/min) "
            f"ETA={eta}"
        )
    if stage == 2:
        # Stage 2 -- liveness. Findings probed is the headline; no per-repo bucket.
        return (
            f"[{now}] stage2 status=checking findings={findings:,} surfaced={surfaced:,} (5m: {findings_rate:+.0f}/min)"
        )
    if stage == 3:
        # Stage 3 -- investigation. Mirror finish_stage3.py: processed/total
        # with yield% over REAL investigations, candidate-insert count, rate,
        # ETA -- not the surfaced count (that flips later at PR-submit).
        buckets = snap.get("inv_buckets", {})
        total_findings_local = findings
        pending = buckets.get("pending", 0)
        processed_findings = total_findings_local - pending
        pct_proc = (100.0 * processed_findings / total_findings_local) if total_findings_local else 0.0
        inv_with = buckets.get("investigated_with_candidate", 0)
        inv_no = buckets.get("investigated_no_candidate", 0)
        derived = buckets.get("derived_candidate", 0)
        real_invs = inv_with + inv_no
        yield_str = f"yield={100.0 * inv_with / real_invs:.1f}%" if real_invs else "yield=n/a"
        skipped_total = (
            buckets.get("skipped_alive", 0) + buckets.get("skipped_language", 0) + buckets.get("skipped_blocklist", 0)
        )
        # Rate based on the processed-findings delta in the rolling window
        # (the findings_window samples track *total* findings; for stage 3
        # the total is fixed and only `pending` shrinks. Pass processed.)
        rate_per_min = _five_min_rate(findings_window)
        eta_local = _eta_str(pending, rate_per_min if rate_per_min > 0 else overall_rate)
        return (
            f"[{now}] stage3 {processed_findings:,}/{total_findings_local:,} ({pct_proc:.1f}%) "
            f"skipped={skipped_total:,} investigated={real_invs:,} {yield_str} "
            f"cands+={derived:,} "
            f"(5m: {rate_per_min:+.0f}/min) ETA={eta_local}"
        )
    if stage == 4:
        return f"[{now}] stage4 scoring surfaced={surfaced:,}{median_str}"
    if stage == 5:
        return f"[{now}] stage5 status={status} surfaced={surfaced:,}/{findings:,}{median_str}"
    return f"[{now}] status={status} (no progress data — stage unknown)"


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
    # Rolling windows: (monotonic_ts, value) per stage's relevant counter.
    # mono_window tracks repo-processed (stage 1).
    # findings_window tracks total_findings (stage 2) -- grows when new URLs probed.
    # stage3_window tracks processed_findings = total - pending (stage 3) -- only
    # this one moves during investigation.
    mono_window: deque = deque(maxlen=10)
    findings_window: deque = deque(maxlen=10)
    stage3_window: deque = deque(maxlen=10)

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

        counts = snap["counts"]
        processed = counts.get("inventoried", 0) + counts.get("error", 0)
        now_mono = time.monotonic()
        mono_window.append((now_mono, processed))
        findings_window.append((now_mono, snap["total_findings"]))
        # stage 3: processed_findings = total - pending. Sample even outside
        # stage 3 so when the transition happens the window already has data.
        pending3 = snap.get("inv_buckets", {}).get("pending", 0)
        stage3_window.append((now_mono, snap["total_findings"] - pending3))

        # Pick the window that matches the current stage so the (5m: ...) rate
        # in the rendered line is the stage's relevant rate.
        stage_for_window = STAGE_MAP.get(snap["status"], 0)
        active_window = stage3_window if stage_for_window == 3 else findings_window

        print(_render(snap, run_id, mono_window, active_window, started_mono), flush=True)

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
