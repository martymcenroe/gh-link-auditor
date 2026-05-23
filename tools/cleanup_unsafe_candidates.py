"""One-time DB cleanup: mark legacy unsafe derived_candidate rows (#275).

PR #274 added a safety filter in ``derive_replacement_prs._is_safely_replaceable``
to skip candidates whose ``str.replace(dead, candidate)`` would corrupt the
surrounding markdown (extractor caught trailing junk into the URL). #274 also
fixed ``bulk_scan.inventory._clean_url_tail`` so future scans don't produce
these rows. But existing rows from prior runs remain in the DB as
``investigation_state='derived_candidate'`` and clutter every tool A summary
with ``(repo, all_candidates_unsafe)`` skip lines.

This script marks those legacy rows ``investigation_state='dropped_unsafe_url'``
so tool A's query (``WHERE investigation_state='derived_candidate'``) stops
picking them up. Idempotent — re-running is a no-op.

Usage::

    poetry run python tools/cleanup_unsafe_candidates.py            # dry-run
    poetry run python tools/cleanup_unsafe_candidates.py --apply    # mutate DB
    poetry run python tools/cleanup_unsafe_candidates.py --db PATH  # alternate DB
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from gh_link_auditor.unified_db import DEFAULT_DB_PATH, UnifiedDatabase  # noqa: E402
from tools.derive_replacement_prs import _is_safely_replaceable  # noqa: E402

DROPPED_STATE = "dropped_unsafe_url"


def _load_unsafe_rows(udb: UnifiedDatabase) -> list[dict]:
    """Find every derived_candidate row that fails the safety filter."""
    rows = udb._conn.execute(
        """SELECT id, repo_full_name, dead_url, candidate_url, source_file, line_number, method
           FROM bulk_scan_findings
           WHERE investigation_state = 'derived_candidate' AND surfaced = 0
           ORDER BY repo_full_name, id"""
    ).fetchall()
    unsafe: list[dict] = []
    for r in rows:
        ok, reason = _is_safely_replaceable(r["dead_url"], r["candidate_url"])
        if not ok:
            row = dict(r)
            row["reason"] = reason
            unsafe.append(row)
    return unsafe


def _mark_dropped(udb: UnifiedDatabase, ids: list[int]) -> None:
    """Set investigation_state='dropped_unsafe_url' for the given row ids."""
    if not ids:
        return
    placeholders = ",".join(["?"] * len(ids))
    udb._conn.execute(
        f"UPDATE bulk_scan_findings SET investigation_state = ? WHERE id IN ({placeholders})",  # noqa: S608
        [DROPPED_STATE, *ids],
    )
    udb._conn.commit()


def _print_preview(unsafe: list[dict]) -> None:
    by_reason: dict[str, int] = {}
    by_repo: dict[str, int] = {}
    for r in unsafe:
        by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
        by_repo[r["repo_full_name"]] = by_repo.get(r["repo_full_name"], 0) + 1

    print(f"unsafe rows: {len(unsafe)} across {len(by_repo)} repos")
    print()
    print("by reason:")
    for reason, n in sorted(by_reason.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {n}")
    print()
    print("rows (first 20):")
    for r in unsafe[:20]:
        loc = r["source_file"]
        if r.get("line_number"):
            loc = f"{loc}:{r['line_number']}"
        print(f"  [{r['id']:>5}] {r['repo_full_name']}  {loc}  ({r['reason']})")
        print(f"          dead: {r['dead_url']}")
        print(f"          cand: {r['candidate_url']}")
    if len(unsafe) > 20:
        print(f"  ... and {len(unsafe) - 20} more")


def cleanup(args: argparse.Namespace) -> int:
    with UnifiedDatabase(args.db) as udb:
        unsafe = _load_unsafe_rows(udb)

        if not unsafe:
            print("no unsafe rows found. nothing to do.")
            return 0

        _print_preview(unsafe)

        if not args.apply:
            print()
            print("[dry-run] no changes made. re-run with --apply to mutate the DB.")
            return 0

        ids = [r["id"] for r in unsafe]
        _mark_dropped(udb, ids)
        print()
        print(f"marked {len(ids)} rows as investigation_state='{DROPPED_STATE}'.")

    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Mark legacy unsafe derived_candidate rows (#275).")
    p.add_argument("--db", default=str(DEFAULT_DB_PATH), help="path to ghla.db")
    p.add_argument("--apply", action="store_true", help="mutate the DB (default is dry-run)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return cleanup(args)


if __name__ == "__main__":
    sys.exit(main())
