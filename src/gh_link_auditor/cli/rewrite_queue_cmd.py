"""CLI subcommand for the rewrite queue (deferred section-rewrite candidates).

Subcommands: list, export, mark-exported, clear. See #212.
"""

from __future__ import annotations

import argparse

from gh_link_auditor.unified_db import DEFAULT_DB_PATH


def build_rewrite_queue_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the rewrite-queue subcommand and its sub-subcommands."""
    rq_parser = subparsers.add_parser(
        "rewrite-queue",
        help="Manage deferred-rewrite queue (operator-flagged dead products / abandoned tools)",
    )
    rq_sub = rq_parser.add_subparsers(dest="rewrite_queue_command")

    # ghla rewrite-queue list
    list_parser = rq_sub.add_parser("list", help="Show pending rewrite-queue entries")
    list_parser.add_argument("--repo", default=None, help="Filter to one repo (owner/name)")
    list_parser.add_argument("--all", action="store_true", help="Include already-exported entries")
    list_parser.add_argument("--db-path", type=str, default=str(DEFAULT_DB_PATH))
    list_parser.set_defaults(func=_cmd_list)

    # ghla rewrite-queue export
    export_parser = rq_sub.add_parser(
        "export",
        help="Print a markdown block ready to paste into an upstream issue",
    )
    export_parser.add_argument("--repo", required=True, help="Repo to export entries for (owner/name)")
    export_parser.add_argument("--db-path", type=str, default=str(DEFAULT_DB_PATH))
    export_parser.set_defaults(func=_cmd_export)

    # ghla rewrite-queue mark-exported
    mark_parser = rq_sub.add_parser(
        "mark-exported",
        help="Mark all unexported entries for a repo as linked to an upstream issue",
    )
    mark_parser.add_argument("--repo", required=True, help="Repo (owner/name)")
    mark_parser.add_argument("--issue", required=True, type=int, help="Upstream issue number")
    mark_parser.add_argument("--db-path", type=str, default=str(DEFAULT_DB_PATH))
    mark_parser.set_defaults(func=_cmd_mark_exported)

    # ghla rewrite-queue clear
    clear_parser = rq_sub.add_parser("clear", help="Hard-delete entries for a repo")
    clear_parser.add_argument("--repo", required=True, help="Repo (owner/name)")
    clear_parser.add_argument("--db-path", type=str, default=str(DEFAULT_DB_PATH))
    clear_parser.set_defaults(func=_cmd_clear)

    rq_parser.set_defaults(func=lambda args: rq_parser.print_help() or 0)


def _get_db(args: argparse.Namespace):
    from gh_link_auditor.unified_db import UnifiedDatabase

    return UnifiedDatabase(args.db_path)


def _cmd_list(args: argparse.Namespace) -> int:
    db = _get_db(args)
    try:
        entries = db.get_rewrite_queue(
            repo_full_name=args.repo,
            include_exported=bool(args.all),
        )
        if not entries:
            scope = f" for {args.repo}" if args.repo else ""
            qual = " (incl. exported)" if args.all else ""
            print(f"No rewrite-queue entries{scope}{qual}.")
            return 0
        for e in entries:
            line_text = f":{e['line_number']}" if e["line_number"] else ""
            state = f"exported to issue #{e['exported_to_issue']}" if e["exported_to_issue"] else "pending"
            print(f"  [{e['id']}] {e['repo_full_name']}  {e['dead_url']}  ({e['source_file']}{line_text})  — {state}")
        return 0
    finally:
        db.close()


def _cmd_export(args: argparse.Namespace) -> int:
    db = _get_db(args)
    try:
        entries = db.get_rewrite_queue(repo_full_name=args.repo, include_exported=False)
        if not entries:
            print(f"No pending entries for {args.repo}.")
            return 0
        print(_format_export_markdown(args.repo, entries))
        return 0
    finally:
        db.close()


def _cmd_mark_exported(args: argparse.Namespace) -> int:
    db = _get_db(args)
    try:
        count = db.mark_rewrite_queue_exported(args.repo, args.issue)
        print(f"marked {count} entr{'y' if count == 1 else 'ies'} as exported to issue #{args.issue}")
        return 0
    finally:
        db.close()


def _cmd_clear(args: argparse.Namespace) -> int:
    db = _get_db(args)
    try:
        count = db.clear_rewrite_queue(args.repo)
        print(f"deleted {count} entr{'y' if count == 1 else 'ies'} for {args.repo}")
        return 0
    finally:
        db.close()


def _format_export_markdown(repo: str, entries: list[dict]) -> str:
    """Render the upstream-issue-ready markdown block. Casual register (#209)."""
    lines = [
        f"the following references in {repo} docs are to discontinued products or abandoned tools",
        "",
        "the dead-link auditor flagged them but they need section-level rewrites not url replacements",
        "",
    ]
    for e in entries:
        line_text = f" line {e['line_number']}" if e["line_number"] else ""
        reason = e["reason"] or "needs rewrite"
        lines.append(f"- {e['dead_url']} in {e['source_file']}{line_text} -- {reason}")
    return "\n".join(lines)
