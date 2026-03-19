"""ghla run — Execute the GHLA pipeline on a target repository.

See LLD #22 §2.4 for CLI specification.
Deviation from LLD: uses argparse instead of click to match codebase stdlib preference.
"""

from __future__ import annotations

import argparse
import sys

from gh_link_auditor.pipeline.graph import run_pipeline
from gh_link_auditor.pipeline.state import create_initial_state


def build_run_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'run' subcommand.

    Args:
        subparsers: The subparsers action from the main parser.
    """
    parser = subparsers.add_parser("run", help="Execute the GHLA pipeline")
    parser.add_argument("target", help="Repository URL or local path")
    parser.add_argument(
        "--max-links",
        type=int,
        default=50,
        help="Circuit breaker threshold (default: 50)",
    )
    parser.add_argument(
        "--max-cost",
        type=float,
        default=5.00,
        help="Cost limit in USD (default: 5.00)",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.8,
        help="Min confidence for auto-approval (default: 0.8)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute N0-N3 only, output verdicts as JSON",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Detailed logging",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Path to state database",
    )
    parser.set_defaults(func=cmd_run)


def cmd_run(args: argparse.Namespace) -> int:
    """Execute the 'run' command.

    Args:
        args: Parsed command line arguments.

    Returns:
        Exit code.
    """
    state = create_initial_state(
        target=args.target,
        max_links=args.max_links,
        max_cost_usd=args.max_cost,
        confidence_threshold=args.confidence,
        dry_run=args.dry_run,
        verbose=args.verbose,
        db_path=args.db_path,
    )

    try:
        result = run_pipeline(state)
    except Exception as exc:
        print(f"Pipeline error: {exc}", file=sys.stderr)
        return 1

    # Determine exit code
    if result.get("circuit_breaker_triggered"):
        count = len(result.get("dead_links", []))
        print(
            f"Circuit breaker triggered: {count} dead links (max: {args.max_links})",
            file=sys.stderr,
        )
        return 2

    if result.get("cost_limit_reached"):
        print(
            f"Cost limit reached (${args.max_cost:.2f})",
            file=sys.stderr,
        )
        return 3

    if result.get("errors"):
        for err in result["errors"]:
            print(f"Error: {err}", file=sys.stderr)
        return 1

    # Success summary
    fixes = result.get("fixes", [])
    dead_links = result.get("dead_links", [])
    verdicts = result.get("verdicts", [])

    if not dead_links:
        print("No dead links found. Documentation is clean!")
        return 0

    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {len(dead_links)} dead links found")
    print(f"{'=' * 60}\n")

    for i, verdict in enumerate(verdicts, 1):
        dl = verdict.get("dead_link", {})
        candidate = verdict.get("candidate")
        confidence = verdict.get("confidence", 0)

        print(f"  [{i}] {dl.get('url', '?')}")
        print(f"      File:       {dl.get('source_file', '?')}:{dl.get('line_number', '?')}")
        print(f"      Status:     {dl.get('http_status', 'unknown')}")
        print(f"      Confidence: {confidence:.0%}")

        if candidate:
            print(f"      Replace:    {candidate['url']}")
            print(f"      Source:     {candidate.get('source', '?')}")
        else:
            print("      Replace:    (no candidate)")

        reasoning = verdict.get("reasoning", "")
        if reasoning:
            print(f"      Reasoning:  {reasoning}")
        print()

    if args.dry_run:
        print(f"Dry-run complete. {len(verdicts)} verdicts produced, no fixes applied.")
    else:
        print(f"Found {len(dead_links)} dead links, generated {len(fixes)} fixes.")

    return 0
