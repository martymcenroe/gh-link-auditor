"""CLI commands for campaign metrics.

See LLD-019 §2.4 for CLI specification.
Subcommands: metrics campaign, metrics refresh, metrics scan-history.
"""

from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_DB_PATH = Path("data/metrics/metrics.db")


def build_metrics_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register metrics subcommands onto the CLI.

    Args:
        subparsers: Parent subparsers action.
    """
    metrics_parser = subparsers.add_parser("metrics", help="Campaign metrics commands")
    metrics_sub = metrics_parser.add_subparsers(dest="metrics_command")

    # metrics campaign
    campaign_parser = metrics_sub.add_parser("campaign", help="Campaign-level metrics")
    campaign_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Metrics DB path")
    campaign_parser.add_argument("--format", choices=["text", "json"], default="text")
    campaign_parser.set_defaults(func=cmd_metrics_campaign)

    # metrics refresh
    refresh_parser = metrics_sub.add_parser("refresh", help="Refresh PR statuses from GitHub")
    refresh_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Metrics DB path")
    refresh_parser.set_defaults(func=cmd_metrics_refresh)

    # metrics scan-history
    history_parser = metrics_sub.add_parser("scan-history", help="Show recent scan history")
    history_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Metrics DB path")
    history_parser.add_argument("--limit", type=int, default=20, help="Max scans to show")
    history_parser.add_argument("--format", choices=["text", "json"], default="text")
    history_parser.set_defaults(func=cmd_metrics_scan_history)


def cmd_metrics_campaign(args: argparse.Namespace) -> int:
    """Display campaign dashboard with aggregate stats and recent PRs.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code.
    """
    from gh_link_auditor.campaign_dashboard import (
        format_dashboard,
        format_dashboard_json,
    )
    from gh_link_auditor.metrics.collector import MetricsCollector
    from gh_link_auditor.metrics.reporter import generate_campaign_metrics

    db_path = Path(args.db_path)
    metrics = generate_campaign_metrics(db_path)

    # Fetch recent PRs for the dashboard
    collector = MetricsCollector(db_path)
    try:
        recent_prs = collector.get_all_pr_outcomes()
    finally:
        collector.close()

    # Sort by submitted_at descending (newest first)
    recent_prs.sort(key=lambda p: p.submitted_at, reverse=True)

    fmt = getattr(args, "format", "text")
    if fmt == "text":
        print(format_dashboard(metrics, recent_prs))
    else:
        import json as json_mod

        data = format_dashboard_json(metrics, recent_prs)
        print(json_mod.dumps(data, indent=2))

    return 0


def cmd_metrics_refresh(args: argparse.Namespace) -> int:
    """Refresh PR statuses from GitHub API.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code.
    """
    from gh_link_auditor.pr_tracker import refresh_pr_outcomes

    db_path = Path(args.db_path)
    updated = refresh_pr_outcomes(db_path)

    if not updated:
        print("No PR status changes detected.")
    else:
        print(f"Updated {len(updated)} PR(s):")
        for outcome in updated:
            print(f"  {outcome.pr_url}: {outcome.status}")

    return 0


def cmd_metrics_scan_history(args: argparse.Namespace) -> int:
    """Display recent scan history.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code.
    """
    from gh_link_auditor.unified_db import UnifiedDatabase

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"No database found at {db_path}")
        return 1

    udb = UnifiedDatabase(db_path)
    try:
        scans = udb.get_recent_scans(limit=args.limit)
    finally:
        udb.close()

    if not scans:
        print("No scan history found.")
        return 0

    fmt = getattr(args, "format", "text")
    if fmt == "json":
        import json as json_mod

        print(json_mod.dumps(scans, indent=2))
    else:
        print(f"{'Repo':<40} {'Started':<20} {'Dead':>5} {'Fixes':>5} {'PR':>3} {'Decision':<15}")
        print("-" * 95)
        for scan in scans:
            repo = (scan.get("repo_full_name") or "unknown")[:39]
            started = (scan.get("started_at") or "")[:19]
            dead = scan.get("dead_links_found", 0)
            fixes = scan.get("fixes_generated", 0)
            pr = "Y" if scan.get("pr_submitted") else "N"
            decision = (scan.get("decision") or "")[:14]
            print(f"{repo:<40} {started:<20} {dead:>5} {fixes:>5} {pr:>3} {decision:<15}")

    return 0
