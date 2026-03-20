"""CLI subcommand for blacklist management.

Provides list, add, remove, and stats operations on the blacklist.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def build_blacklist_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the blacklist subcommand and its sub-subcommands."""
    bl_parser = subparsers.add_parser("blacklist", help="Manage repo/maintainer blacklist")
    bl_sub = bl_parser.add_subparsers(dest="blacklist_command")

    # ghla blacklist list
    list_parser = bl_sub.add_parser("list", help="Show active blacklist entries")
    list_parser.add_argument("--db-path", type=str, default=None)
    list_parser.set_defaults(func=_cmd_list)

    # ghla blacklist add
    add_parser = bl_sub.add_parser("add", help="Manually blacklist a repo")
    add_parser.add_argument("repo_url", help="Repository URL to blacklist")
    add_parser.add_argument("--reason", default="manual blacklist", help="Reason")
    add_parser.add_argument("--db-path", type=str, default=None)
    add_parser.set_defaults(func=_cmd_add)

    # ghla blacklist remove
    rm_parser = bl_sub.add_parser("remove", help="Remove a blacklist entry by ID")
    rm_parser.add_argument("entry_id", type=int, help="Blacklist entry ID")
    rm_parser.add_argument("--db-path", type=str, default=None)
    rm_parser.set_defaults(func=_cmd_remove)

    # ghla blacklist stats
    stats_parser = bl_sub.add_parser("stats", help="Show blacklist statistics by source")
    stats_parser.add_argument("--db-path", type=str, default=None)
    stats_parser.set_defaults(func=_cmd_stats)

    bl_parser.set_defaults(func=lambda args: bl_parser.print_help() or 0)


def _get_db(args: argparse.Namespace):
    from gh_link_auditor.unified_db import UnifiedDatabase

    db_path = args.db_path or str(Path.home() / ".ghla" / "ghla.db")
    return UnifiedDatabase(db_path)


def _cmd_list(args: argparse.Namespace) -> int:
    db = _get_db(args)
    try:
        entries = db.get_blacklist()
        if not entries:
            print("No active blacklist entries.")
            return 0
        for e in entries:
            target = e.repo_url or f"maintainer:{e.maintainer}"
            expires = f" (expires {e.expires_at.isoformat()})" if e.expires_at else " (permanent)"
            print(f"  [{e.id}] {target} — {e.reason}{expires}")
        return 0
    finally:
        db.close()


def _cmd_add(args: argparse.Namespace) -> int:
    db = _get_db(args)
    try:
        entry_id = db.add_to_blacklist(repo_url=args.repo_url, reason=args.reason, source="manual")
        print(f"Added blacklist entry [{entry_id}]: {args.repo_url}")
        return 0
    finally:
        db.close()


def _cmd_remove(args: argparse.Namespace) -> int:
    db = _get_db(args)
    try:
        if db.remove_from_blacklist(args.entry_id):
            print(f"Removed blacklist entry [{args.entry_id}]")
            return 0
        print(f"Entry [{args.entry_id}] not found")
        return 1
    finally:
        db.close()


def _cmd_stats(args: argparse.Namespace) -> int:
    db = _get_db(args)
    try:
        by_source = db.get_blacklist_by_source()
        if not by_source:
            print("No active blacklist entries.")
            return 0
        total = sum(by_source.values())
        print(f"Active blacklist entries: {total}")
        for source, count in sorted(by_source.items()):
            print(f"  {source}: {count}")
        return 0
    finally:
        db.close()
