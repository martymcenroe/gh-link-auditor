"""CLI main entry point for gh-link-auditor.

Provides the `ghla` command with subcommands.
"""

from __future__ import annotations

import argparse
import logging
import sys
import warnings

# Suppress Pydantic V1 compatibility warning from langchain-core on Python 3.14+
# Must be set before any langgraph/langchain imports are triggered.
warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")

from gh_link_auditor.cli.batch_cmd import build_batch_parser  # noqa: E402
from gh_link_auditor.cli.blacklist_cmd import build_blacklist_parser  # noqa: E402
from gh_link_auditor.cli.bulk_scan_cmd import build_bulk_scan_parser  # noqa: E402
from gh_link_auditor.cli.metrics_cmd import build_metrics_parser  # noqa: E402
from gh_link_auditor.cli.recheck_cmd import build_recheck_parser  # noqa: E402
from gh_link_auditor.cli.rewrite_queue_cmd import build_rewrite_queue_parser  # noqa: E402
from gh_link_auditor.cli.run import build_run_parser  # noqa: E402


def _configure_logging(level: int) -> None:
    """Route library loggers to stderr so long-running commands stream
    progress to the operator's console instead of going silent for hours.

    Previously the CLI did not call logging.basicConfig at all, which
    meant every logger.info(...) across bulk-scan, preflight, liveness,
    investigation, etc. went to the default null handler. Multi-hour
    runs appeared frozen even though work was happening.

    force=True replaces any handler imported libraries may have
    configured first (e.g. langchain). Without it, basicConfig would
    be a no-op when handlers already exist.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
        force=True,
    )
    # Knock down third-party noise so the gh_link_auditor signal stays
    # readable. -vv re-enables DEBUG on these.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    """Build the main argument parser.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        prog="ghla",
        description="gh-link-auditor: Dead link resolution pipeline",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity: -v = DEBUG from gh_link_auditor; -vv = DEBUG everywhere including httpx",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress INFO-level progress; only WARNING/ERROR are shown",
    )
    subparsers = parser.add_subparsers(dest="command")

    build_run_parser(subparsers)
    build_batch_parser(subparsers)
    build_blacklist_parser(subparsers)
    build_bulk_scan_parser(subparsers)
    build_metrics_parser(subparsers)
    build_recheck_parser(subparsers)
    build_rewrite_queue_parser(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the CLI.

    Args:
        argv: Command line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code.
    """
    from dotenv import load_dotenv

    load_dotenv()

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.quiet:
        _configure_logging(logging.WARNING)
    elif args.verbose >= 2:
        _configure_logging(logging.DEBUG)
        for noisy in ("httpx", "httpcore", "urllib3"):
            logging.getLogger(noisy).setLevel(logging.DEBUG)
    elif args.verbose == 1:
        _configure_logging(logging.DEBUG)
    else:
        _configure_logging(logging.INFO)

    if not args.command:
        parser.print_help()
        return 0

    if hasattr(args, "func"):
        return args.func(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
