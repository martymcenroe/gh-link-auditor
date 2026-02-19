"""CLI main entry point for gh-link-auditor.

Provides the `ghla` command with subcommands.
"""

from __future__ import annotations

import argparse
import sys

from gh_link_auditor.cli.run import build_run_parser


def build_parser() -> argparse.ArgumentParser:
    """Build the main argument parser.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        prog="ghla",
        description="gh-link-auditor: Dead link resolution pipeline",
    )
    subparsers = parser.add_subparsers(dest="command")

    build_run_parser(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the CLI.

    Args:
        argv: Command line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if hasattr(args, "func"):
        return args.func(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
