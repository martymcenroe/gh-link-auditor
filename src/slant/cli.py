"""CLI entry point for Slant scoring engine.

Provides ``score`` and ``dashboard`` subcommands via argparse.

Usage:
    python -m slant score --report report.json [--output verdicts.json] [--weights weights.json]
    python -m slant dashboard --verdicts verdicts.json [--port 8913]

See LLD #21 §2.4 for specification.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from slant.config import load_weights
from slant.scorer import score_report, write_verdicts


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point.

    Args:
        argv: Command-line arguments, or None for sys.argv.

    Returns:
        Exit code (0 for success).
    """
    parser = argparse.ArgumentParser(
        prog="slant",
        description="Mr. Slant — Scoring engine for dead link replacement candidates",
    )
    subparsers = parser.add_subparsers(dest="command")

    # score subcommand
    score_parser = subparsers.add_parser("score", help="Score a forensic report")
    score_parser.add_argument("--report", required=True, type=Path, help="Path to forensic report JSON")
    score_parser.add_argument("--output", type=Path, default=None, help="Output path for verdicts JSON")
    score_parser.add_argument("--weights", type=Path, default=None, help="Path to weights config JSON")

    # dashboard subcommand
    dashboard_parser = subparsers.add_parser("dashboard", help="Start HITL review dashboard")
    dashboard_parser.add_argument("--verdicts", required=True, type=Path, help="Path to verdicts JSON")
    dashboard_parser.add_argument("--port", type=int, default=8913, help="Dashboard port (default: 8913)")

    args = parser.parse_args(argv)

    if args.command == "score":
        return cmd_score(args)
    elif args.command == "dashboard":
        return cmd_dashboard(args)
    else:
        parser.print_help()
        return 0


def cmd_score(args: argparse.Namespace) -> int:
    """Handle 'score' subcommand.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code.
    """
    weights = load_weights(args.weights)
    result = score_report(args.report, weights)

    # Determine output path
    output_path = args.output
    if output_path is None:
        output_path = args.report.parent / "verdicts.json"

    write_verdicts(result, output_path)

    # Print summary
    tiers: dict[str, int] = {}
    for v in result["verdicts"]:
        tier = v["verdict"]
        tiers[tier] = tiers.get(tier, 0) + 1

    print(f"Scored {len(result['verdicts'])} dead links:")
    for tier, count in sorted(tiers.items()):
        print(f"  {tier}: {count}")
    print(f"Verdicts written to: {output_path}")

    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Handle 'dashboard' subcommand.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code.
    """
    from slant.dashboard import start_dashboard

    start_dashboard(args.verdicts, port=args.port)
    return 0
