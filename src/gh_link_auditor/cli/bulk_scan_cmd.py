"""CLI subcommand for the bulk scan (#218).

Subcommands: start, status, stop, report, list-runs.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

from gh_link_auditor.bulk_scan import scoring, storage
from gh_link_auditor.bulk_scan.config import (
    ABORT_FILE,
    DEFAULT_TARGET_REPO_COUNT,
    REPORT_FILE,
)
from gh_link_auditor.unified_db import DEFAULT_DB_PATH, UnifiedDatabase

logger = logging.getLogger(__name__)


def build_bulk_scan_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "bulk-scan",
        help="Unattended bulk scan across many repos (#218)",
    )
    sub = parser.add_subparsers(dest="bulk_scan_command")

    start = sub.add_parser("start", help="Start (or resume) a bulk scan run")
    start.add_argument("--target", type=int, default=DEFAULT_TARGET_REPO_COUNT)
    start.add_argument("--run-id", default=None, help="Existing run_id to resume (else timestamped)")
    start.add_argument("--db-path", type=str, default=str(DEFAULT_DB_PATH))
    start.add_argument("--token", type=str, default=None, help="GITHUB_TOKEN override")
    start.set_defaults(func=_cmd_start)

    status = sub.add_parser("status", help="Print status snapshot for the most-recent (or given) run")
    status.add_argument("--run-id", default=None)
    status.add_argument("--db-path", type=str, default=str(DEFAULT_DB_PATH))
    status.set_defaults(func=_cmd_status)

    stop = sub.add_parser("stop", help="Request graceful stop (writes abort marker)")
    stop.set_defaults(func=_cmd_stop)

    report = sub.add_parser("report", help="Render the ranked markdown report")
    report.add_argument("--run-id", required=True)
    report.add_argument("--db-path", type=str, default=str(DEFAULT_DB_PATH))
    report.add_argument("--out", type=str, default=REPORT_FILE)
    report.set_defaults(func=_cmd_report)

    listr = sub.add_parser("list-runs", help="List recent bulk-scan runs")
    listr.add_argument("--db-path", type=str, default=str(DEFAULT_DB_PATH))
    listr.set_defaults(func=_cmd_list_runs)

    parser.set_defaults(func=lambda args: parser.print_help() or 0)


def _cmd_start(args: argparse.Namespace) -> int:
    from gh_link_auditor.bulk_scan import runner

    run_id = args.run_id or f"bulk-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    print(f"starting bulk-scan run: {run_id}")
    print(f"target: {args.target} repos | db: {args.db_path}")
    print(f"heartbeat: see {Path('data/bulk-scan-heartbeat.txt').resolve()}")
    print(f"abort marker: touch {ABORT_FILE} to stop gracefully")
    with UnifiedDatabase(args.db_path) as db:
        result = runner.run_full(db, run_id, args.target, token=args.token)
        print(f"final status: {result.get('status')}")
        return 0 if result.get("status") == "done" else 2


def _cmd_status(args: argparse.Namespace) -> int:
    with UnifiedDatabase(args.db_path) as db:
        run_id = args.run_id
        if run_id is None:
            runs = storage.list_runs(db, limit=1)
            if not runs:
                print("no runs found")
                return 0
            run_id = runs[0]["run_id"]
        run = storage.get_run(db, run_id)
        if run is None:
            print(f"run not found: {run_id}")
            return 1
        counts = storage.get_repo_count_by_status(db, run_id)
        total = storage.count_findings(db, run_id)
        surfaced = storage.count_findings(db, run_id, surfaced=True)
        median = scoring.quality_sample_median(db, run_id)
        print(f"run_id:           {run_id}")
        print(f"status:           {run['status']}")
        print(f"started_at:       {run['started_at']}")
        print(f"completed_at:     {run.get('completed_at')}")
        print(f"target_count:     {run.get('target_repo_count')}")
        print(f"repos_by_status:  {counts}")
        print(f"total_findings:   {total}")
        print(f"surfaced:         {surfaced}")
        if median is not None:
            print(f"sample_median:    {median:.2f}")
        if run.get("quality_aborted"):
            print("QUALITY_ABORTED:  yes")
        return 0


def _cmd_stop(args: argparse.Namespace) -> int:
    p = Path(ABORT_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    print(f"stop requested: {p.resolve()}")
    print("the running scan will exit at the next batch boundary")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    with UnifiedDatabase(args.db_path) as db:
        body = scoring.render_ranked_report(db, args.run_id)
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    print(f"report written: {p.resolve()}")
    return 0


def _cmd_list_runs(args: argparse.Namespace) -> int:
    with UnifiedDatabase(args.db_path) as db:
        runs = storage.list_runs(db, limit=20)
    if not runs:
        print("no runs found")
        return 0
    for r in runs:
        print(f"  {r['run_id']}  {r['status']}  started={r['started_at']}  done={r.get('completed_at') or '-'}")
    return 0
