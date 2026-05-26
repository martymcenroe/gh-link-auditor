"""Reset a bulk-scan run from quality_aborted back to investigating.

Operational recovery for runs that the (now-permanently-disabled, #362)
quality stop-loss killed mid-flight. The run's url_check_cache and
findings rows are intact; only the run-level status needs to flip so
`bulk-scan start --run-id <id>` resumes from Stage 3 instead of refusing.

Why a script instead of a one-liner: PowerShell quoting around sqlite3
+ embedded SQL is genuinely fragile. This removes the quoting risk and
prints exactly what changed so you can see it worked.

Usage::

    poetry run python tools/reset_quality_aborted.py
    poetry run python tools/reset_quality_aborted.py --run-id bulk-20260526T031148Z
    poetry run python tools/reset_quality_aborted.py --dry-run

Default run-id is ``bulk-20260526T031148Z`` (the 2026-05-26 incident).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DEFAULT_RUN_ID = "bulk-20260526T031148Z"
DEFAULT_DB_PATH = Path.home() / ".ghla" / "ghla.db"


def _explain_status(status: str | None) -> str:
    if status == "quality_aborted":
        return "quality_aborted  -- scan was killed mid-flight; will NOT resume in this state"
    if status == "investigating":
        return "investigating    -- Stage 3 ready; 'bulk-scan start --run-id' will resume here"
    if status == "aborted":
        return "aborted          -- operator stopped the scan; resumable"
    if status == "done":
        return "done             -- scan completed normally"
    if status in {"selecting", "inventorying", "checking", "scoring"}:
        return f"{status:16s} -- mid-stage; intentional reset is unusual"
    return f"{status!r}"


def _explain_quality_aborted(v: int | None) -> str:
    if v == 1:
        return "yes  -- the kill flag set by the now-disabled quality stop-loss (#362)"
    if v == 0:
        return "no   -- the scan is in a clean state"
    return f"{v!r}"


def _explain_completed_at(v: str | None) -> str:
    if v is None:
        return "(unset; the scan has not finished, which is what we want for resume)"
    return f"{v}  -- stamped when the scan exited; must be cleared to resume"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--run-id",
        default=DEFAULT_RUN_ID,
        help=f"run_id to reset (default: {DEFAULT_RUN_ID})",
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help=f"path to ghla.db (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would change without writing",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    if not db_path.exists():
        sys.stderr.write(f"DB not found: {db_path}\n")
        return 2

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT status, quality_aborted, completed_at FROM bulk_scan_runs WHERE run_id = ?",
            (args.run_id,),
        ).fetchone()
        if row is None:
            sys.stderr.write(f"run not found: {args.run_id!r}\n")
            return 3

        print(f"run_id:  {args.run_id}")
        print(f"db:      {db_path}")
        print()
        print("BEFORE:")
        print(f"  status:           {_explain_status(row['status'])}")
        print(f"  quality_aborted:  {_explain_quality_aborted(row['quality_aborted'])}")
        print(f"  completed_at:     {_explain_completed_at(row['completed_at'])}")

        already_clean = row["status"] == "investigating" and not row["quality_aborted"]
        if already_clean:
            print()
            print("nothing to do -- the run is already in 'investigating' with quality_aborted=0.")
            return 0

        if args.dry_run:
            after_status: str | None = "investigating"
            after_qa: int | None = 0
            after_completed_at: str | None = None
        else:
            con.execute(
                "UPDATE bulk_scan_runs SET status = ?, quality_aborted = ?, completed_at = ? WHERE run_id = ?",
                ("investigating", 0, None, args.run_id),
            )
            con.commit()
            verified = con.execute(
                "SELECT status, quality_aborted, completed_at FROM bulk_scan_runs WHERE run_id = ?",
                (args.run_id,),
            ).fetchone()
            after_status = verified["status"]
            after_qa = verified["quality_aborted"]
            after_completed_at = verified["completed_at"]

        print()
        print("AFTER (projected; not written):" if args.dry_run else "AFTER:")
        print(f"  status:           {_explain_status(after_status)}")
        print(f"  quality_aborted:  {_explain_quality_aborted(after_qa)}")
        print(f"  completed_at:     {_explain_completed_at(after_completed_at)}")

        if args.dry_run:
            print()
            print("re-run without --dry-run to apply.")
            return 0

        print()
        print("resume with:")
        print(f"  poetry run python -m gh_link_auditor.cli.main bulk-scan start --run-id {args.run_id}")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
