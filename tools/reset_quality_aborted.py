"""Reset a bulk-scan run from quality_aborted back to checking.

Operational recovery for runs that the (now-permanently-disabled, #362)
quality stop-loss killed mid-flight. The run's url_check_cache and
findings rows are intact; flipping the run-level status to ``'checking'``
lets ``bulk-scan start --run-id <id>`` resume cleanly through Stage 2's
cache lookup and into Stage 3 with a populated liveness_results dict.

Why 'checking' and NOT 'investigating': audit lesson 2026-05-22 (R6 /
LLD-244) -- resetting to 'investigating' skips Stage 2 entirely, so
Stage 3 sees an empty liveness_results, and `runner.py:307-313`'s "URL
is alive" branch fires on every pending finding. The 2026-05-26 13:10
incident saw 22,863 findings stamped 'skipped_alive' in 48 seconds for
exactly this reason.

This script also recovers findings whose ``investigation_state`` is
'skipped_alive' but whose ``url_check_cache.http_status`` is NULL or
>= 400 -- those were mis-stamped by an earlier bad reset and need to
go back to 'pending' so Stage 3 can investigate them.

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
RESET_TARGET_STATUS = "checking"


def _explain_status(status: str | None) -> str:
    if status == "quality_aborted":
        return "quality_aborted  -- scan was killed mid-flight; will NOT resume in this state"
    if status == "checking":
        return "checking         -- Stage 2 ready; 'bulk-scan start --run-id' will resume here"
    if status == "investigating":
        return (
            "investigating    -- Stage 3 ready in theory, BUT this state skips Stage 2 and "
            "mis-classifies pending findings as alive (#392). Always reset to 'checking' instead."
        )
    if status == "aborted":
        return "aborted          -- operator stopped the scan; resumable"
    if status == "done":
        return "done             -- scan completed normally"
    if status in {"selecting", "inventorying", "scoring"}:
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


def _count_mis_stamped(con: sqlite3.Connection, run_id: str) -> int:
    """Count findings whose investigation_state is 'skipped_alive' but
    whose url_check_cache entry contradicts that (no cache OR status >= 400).

    These are the rows that an earlier bad reset to 'investigating'
    incorrectly stamped. They need to go back to 'pending' so Stage 3
    can investigate them."""
    row = con.execute(
        """
        SELECT COUNT(*) AS n
        FROM bulk_scan_findings bsf
        LEFT JOIN url_check_cache ucc ON ucc.url = bsf.dead_url
        WHERE bsf.run_id = ?
          AND bsf.method = 'pending'
          AND bsf.investigation_state = 'skipped_alive'
          AND (ucc.http_status IS NULL OR ucc.http_status >= 400)
        """,
        (run_id,),
    ).fetchone()
    return int(row["n"])


def _recover_mis_stamped(con: sqlite3.Connection, run_id: str) -> int:
    """Flip mis-stamped 'skipped_alive' findings back to 'pending'.
    Returns the number of rows affected."""
    cur = con.execute(
        """
        UPDATE bulk_scan_findings
        SET investigation_state = 'pending',
            investigation_completed_at = NULL
        WHERE run_id = ?
          AND method = 'pending'
          AND investigation_state = 'skipped_alive'
          AND dead_url IN (
              SELECT bsf2.dead_url
              FROM bulk_scan_findings bsf2
              LEFT JOIN url_check_cache ucc ON ucc.url = bsf2.dead_url
              WHERE bsf2.run_id = ?
                AND (ucc.http_status IS NULL OR ucc.http_status >= 400)
          )
        """,
        (run_id, run_id),
    )
    return cur.rowcount


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

        mis_stamped_before = _count_mis_stamped(con, args.run_id)

        print(f"run_id:  {args.run_id}")
        print(f"db:      {db_path}")
        print()
        print("BEFORE:")
        print(f"  status:           {_explain_status(row['status'])}")
        print(f"  quality_aborted:  {_explain_quality_aborted(row['quality_aborted'])}")
        print(f"  completed_at:     {_explain_completed_at(row['completed_at'])}")
        print(
            f"  mis-stamped:      {mis_stamped_before:,}  -- findings marked 'skipped_alive' "
            "but cache says NOT alive; need to go back to 'pending'"
        )

        run_status_clean = row["status"] == RESET_TARGET_STATUS and not row["quality_aborted"]
        already_clean = run_status_clean and mis_stamped_before == 0
        if already_clean:
            print()
            print(
                f"nothing to do -- the run is already at '{RESET_TARGET_STATUS}', "
                "quality_aborted=0, and no mis-stamped findings."
            )
            return 0

        if args.dry_run:
            after_status: str | None = RESET_TARGET_STATUS
            after_qa: int | None = 0
            after_completed_at: str | None = None
            after_mis_stamped = 0
            recovered_count = mis_stamped_before
        else:
            con.execute(
                "UPDATE bulk_scan_runs SET status = ?, quality_aborted = ?, completed_at = ? WHERE run_id = ?",
                (RESET_TARGET_STATUS, 0, None, args.run_id),
            )
            recovered_count = _recover_mis_stamped(con, args.run_id)
            con.commit()
            verified = con.execute(
                "SELECT status, quality_aborted, completed_at FROM bulk_scan_runs WHERE run_id = ?",
                (args.run_id,),
            ).fetchone()
            after_status = verified["status"]
            after_qa = verified["quality_aborted"]
            after_completed_at = verified["completed_at"]
            after_mis_stamped = _count_mis_stamped(con, args.run_id)

        print()
        print("AFTER (projected; not written):" if args.dry_run else "AFTER:")
        print(f"  status:           {_explain_status(after_status)}")
        print(f"  quality_aborted:  {_explain_quality_aborted(after_qa)}")
        print(f"  completed_at:     {_explain_completed_at(after_completed_at)}")
        print(f"  mis-stamped:      {after_mis_stamped:,}  -- remaining after recovery")
        print(
            f"  recovered:        {recovered_count:,}  -- findings flipped from 'skipped_alive' "
            "back to 'pending' for re-investigation"
        )

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
