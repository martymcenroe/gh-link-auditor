"""CLI subcommand for recheck queue management.

Provides the `ghla recheck` command to process snoozed findings
that are due for re-verification.

See issue #148 for specification.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def build_recheck_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the recheck subcommand."""
    rc_parser = subparsers.add_parser("recheck", help="Process snoozed findings due for recheck")
    rc_parser.add_argument("--db-path", type=str, default=None, help="Path to GHLA database")
    rc_parser.add_argument("--dry-run", action="store_true", help="Show what would be rechecked without acting")
    rc_parser.set_defaults(func=cmd_recheck)


def _check_url(url: str) -> dict:
    """Thin wrapper around network.check_url for testability.

    Imported lazily to avoid pulling in httpx at CLI parse time.
    """
    from gh_link_auditor.network import check_url

    return check_url(url)


def cmd_recheck(args: argparse.Namespace) -> int:
    """Execute the recheck command.

    Queries due rechecks, checks each URL, and updates status.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 for success).
    """
    from gh_link_auditor.unified_db import UnifiedDatabase

    db_path = args.db_path or str(Path.home() / ".ghla" / "ghla.db")
    dry_run = args.dry_run

    with UnifiedDatabase(db_path) as db:
        due = db.get_due_rechecks()

        if not due:
            print("No rechecks due.")
            return 0

        print(f"Found {len(due)} snoozed finding(s) due for recheck.\n")

        resolved = 0
        confirmed_dead = 0
        re_snoozed = 0

        for entry in due:
            url = entry["url"]
            recheck_count = entry["recheck_count"]
            entry_id = entry["id"]

            print(f"  Checking: {url}")
            print(f"    Repo: {entry['repo_full_name']}")
            print(f"    File: {entry['source_file']}")
            print(f"    Recheck #{recheck_count + 1}")

            if dry_run:
                print("    [dry-run] Would check URL\n")
                continue

            result = _check_url(url)
            status_code = result.get("status_code")
            is_live = result["status"] == "ok" and status_code is not None and status_code < 400

            if is_live:
                db.complete_recheck(entry_id, "resolved")
                resolved += 1
                print(f"    -> RESOLVED (status {status_code})\n")
            elif recheck_count >= 2:
                # Already checked 2 times before, this is the 3rd: confirm dead
                db.complete_recheck(entry_id, "confirmed_dead")
                confirmed_dead += 1
                print(f"    -> CONFIRMED DEAD (status {status_code}, {recheck_count + 1} checks)\n")
            else:
                db.increment_recheck(entry_id, snooze_days=7)
                re_snoozed += 1
                print(f"    -> Still dead (status {status_code}), re-snoozed 7 days\n")

        if not dry_run:
            print("--- Recheck Summary ---")
            print(f"  Resolved:       {resolved}")
            print(f"  Confirmed dead: {confirmed_dead}")
            print(f"  Re-snoozed:     {re_snoozed}")

        # Show overall queue stats
        stats = db.get_recheck_stats()
        print("\n--- Queue Stats ---")
        print(f"  Pending:        {stats['pending']}")
        print(f"  Resolved:       {stats['resolved']}")
        print(f"  Confirmed dead: {stats['confirmed_dead']}")

    return 0
