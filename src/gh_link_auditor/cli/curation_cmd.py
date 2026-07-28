"""CLI for the merge-graduation curation surface (#404).

A merged campaign PR is the strongest receptiveness signal the campaign
produces: the maintainer reviewed contributor code, accepted it, and merged
it. Those repos are where deeper contributor effort has asymmetric payoff.
This surface lists them and holds the operator's triage decision so the list
shrinks as calls get made.

Subcommands:
    curation list                     graduated repos + triage state
    curation set <repo> --status ...  record a triage decision
"""

from __future__ import annotations

import argparse
import json as json_mod
from datetime import datetime, timezone

from gh_link_auditor.unified_db import DEFAULT_DB_PATH, UnifiedDatabase

STATUSES = ["unseen", "evaluating", "actively-contributing", "passed-on"]


def build_curation_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the curation subcommands."""
    parser = subparsers.add_parser(
        "curation",
        help="Repos that merged a campaign PR — candidates for real contributor work (#404)",
    )
    sub = parser.add_subparsers(dest="curation_command")

    lst = sub.add_parser("list", help="List merge-graduated repos with triage state")
    lst.add_argument("--db-path", type=str, default=str(DEFAULT_DB_PATH))
    lst.add_argument("--format", choices=["text", "json"], default="text")
    lst.add_argument(
        "--status",
        choices=STATUSES,
        default=None,
        help="Only show entries in this triage state",
    )
    lst.add_argument(
        "--all",
        action="store_true",
        help="Include entries already marked passed-on (hidden by default)",
    )
    lst.add_argument(
        "--refresh",
        action="store_true",
        help="Fetch current stars/contributors/last-push from GitHub and store them (default: offline)",
    )
    lst.set_defaults(func=cmd_curation_list)

    st = sub.add_parser("set", help="Record a triage decision for a repo")
    st.add_argument("repo", help="Repo as owner/name")
    st.add_argument("--status", choices=STATUSES, required=True)
    st.add_argument("--notes", default=None, help="Freeform notes (omit to keep existing)")
    st.add_argument("--db-path", type=str, default=str(DEFAULT_DB_PATH))
    st.set_defaults(func=cmd_curation_set)

    parser.set_defaults(func=lambda args: parser.print_help() or 0)


def _days_since(iso: str | None) -> str:
    if not iso:
        return "?"
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "?"
    days = (datetime.now(timezone.utc) - then).days
    return f"{days}d"


def _refresh_signals(db: UnifiedDatabase, rows: list[dict]) -> None:
    """Populate stars/contributors/pushed_at for graduated repos.

    Offline by default because this surface is browsed repeatedly; the size
    signals only matter when the operator is actually weighing where to
    invest, and they change slowly.
    """
    from gh_link_auditor.repo_quality import fetch_repo_metadata

    for r in rows:
        owner, _, name = r["full_name"].partition("/")
        try:
            meta = fetch_repo_metadata(owner, name)
        except Exception:  # noqa: BLE001 - a refresh failure must not hide the list
            continue
        db.upsert_repo(
            r["full_name"],
            stars=meta.stars or None,
            contributors=meta.contributors or None,
            pushed_at=meta.pushed_at or None,
        )


def cmd_curation_list(args: argparse.Namespace) -> int:
    """List graduated repos. Exit 0 even when empty (not an error state)."""
    with UnifiedDatabase(args.db_path) as db:
        rows = db.get_graduated_repos()
        if getattr(args, "refresh", False) and rows:
            _refresh_signals(db, rows)
            rows = db.get_graduated_repos()

    if args.status:
        rows = [r for r in rows if r["status"] == args.status]
    elif not args.all:
        rows = [r for r in rows if r["status"] != "passed-on"]

    if args.format == "json":
        print(json_mod.dumps(rows, indent=2, default=str))
        return 0

    if not rows:
        print("No merge-graduated repos yet.")
        print("A repo graduates when one of our campaign PRs is merged; run")
        print("`metrics refresh` first if a merge landed since the last poll.")
        return 0

    print(f"{len(rows)} repo(s) have merged a campaign PR — candidates for real contributor work:")
    print()
    for r in rows:
        merged = (r.get("first_merge_at") or "")[:10] or "?"
        stars = r.get("stars")
        contribs = r.get("contributors")
        print(f"  {r['full_name']}")
        print(f"    status:     {r['status']}")
        print(f"    first merge: {merged}   merges: {r.get('total_merges', 0)}/{r.get('total_prs', 0)} PRs")
        print(
            f"    signals:    stars={stars if stars is not None else '?'} "
            f"contributors={contribs if contribs is not None else '?'} "
            f"last push={_days_since(r.get('pushed_at'))} ago"
        )
        print(f"    maintainer: https://github.com/{r['full_name'].split('/')[0]}")
        print(
            f"    good first issues: https://github.com/{r['full_name']}/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22"
        )
        if r.get("notes"):
            print(f"    notes:      {r['notes']}")
        print()

    print("Record a decision:")
    print("  ghla curation set <owner/repo> --status evaluating --notes '...'")
    return 0


def cmd_curation_set(args: argparse.Namespace) -> int:
    """Persist a triage decision. Exit 1 if the repo has not graduated."""
    with UnifiedDatabase(args.db_path) as db:
        graduated = {r["full_name"] for r in db.get_graduated_repos()}
        if args.repo not in graduated:
            print(f"ERROR: {args.repo} has not merged a campaign PR — nothing to curate.")
            print("Only merge-graduated repos appear on this surface.")
            return 1
        db.set_curation(args.repo, args.status, args.notes)
    note_suffix = " (notes updated)" if args.notes is not None else ""
    print(f"{args.repo}: status set to {args.status}{note_suffix}")
    return 0
