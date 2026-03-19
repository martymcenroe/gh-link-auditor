"""CLI commands for campaign metrics.

See LLD-019 §2.4 for CLI specification.
Subcommands: metrics campaign, metrics refresh.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from gh_link_auditor.metrics.reporter import (
    format_campaign_text,
    generate_campaign_metrics,
)

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


def cmd_metrics_campaign(args: argparse.Namespace) -> int:
    """Display campaign metrics.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code.
    """
    db_path = Path(args.db_path)
    metrics = generate_campaign_metrics(db_path)

    fmt = getattr(args, "format", "text")
    if fmt == "text":
        print(format_campaign_text(metrics))
    else:
        import json as json_mod

        data = {
            "total_runs": metrics.total_runs,
            "total_repos_processed": metrics.total_repos_processed,
            "total_prs_submitted": metrics.total_prs_submitted,
            "total_prs_merged": metrics.total_prs_merged,
            "total_prs_rejected": metrics.total_prs_rejected,
            "total_prs_open": metrics.total_prs_open,
            "acceptance_rate": metrics.acceptance_rate,
            "avg_time_to_merge_hours": metrics.avg_time_to_merge_hours,
            "rejection_reasons": metrics.rejection_reasons,
        }
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
