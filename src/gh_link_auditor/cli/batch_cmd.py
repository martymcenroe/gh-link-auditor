"""CLI commands for batch execution.

See LLD-019 §2.4 for CLI specification.
Subcommands: batch run, batch resume, batch status, batch cleanup.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from gh_link_auditor.batch.cleanup import check_disk_usage
from gh_link_auditor.batch.engine import _load_checkpoint, resume_batch, run_batch
from gh_link_auditor.batch.models import BatchConfig, TaskStatus
from gh_link_auditor.metrics.reporter import format_report_json, format_report_text


def build_batch_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register batch subcommands onto the CLI.

    Args:
        subparsers: Parent subparsers action.
    """
    batch_parser = subparsers.add_parser("batch", help="Batch execution commands")
    batch_sub = batch_parser.add_subparsers(dest="batch_command")

    # batch run
    run_parser = batch_sub.add_parser("run", help="Run batch against target list")
    run_parser.add_argument("--target-list", required=True, help="Path to Repo Scout JSON")
    run_parser.add_argument("--concurrency", type=int, default=1, help="Worker count")
    run_parser.add_argument("--dry-run", action="store_true", help="Skip PR submission")
    run_parser.add_argument("--max-repos", type=int, default=None, help="Cap on repos")
    run_parser.add_argument("--format", choices=["text", "json"], default="text")
    run_parser.set_defaults(func=cmd_batch_run)

    # batch resume
    resume_parser = batch_sub.add_parser("resume", help="Resume from checkpoint")
    resume_parser.add_argument("--checkpoint", required=True, help="Checkpoint file")
    resume_parser.add_argument("--format", choices=["text", "json"], default="text")
    resume_parser.set_defaults(func=cmd_batch_resume)

    # batch status
    status_parser = batch_sub.add_parser("status", help="Show batch status")
    status_parser.add_argument("--checkpoint", required=True, help="Checkpoint file")
    status_parser.set_defaults(func=cmd_batch_status)

    # batch cleanup
    cleanup_parser = batch_sub.add_parser("cleanup", help="Cleanup clones and branches")
    cleanup_parser.add_argument("--clone-dir", required=True, help="Clone directory")
    cleanup_parser.add_argument("--prune-forks", action="store_true", help="Also prune stale forks")
    cleanup_parser.set_defaults(func=cmd_batch_cleanup)


def cmd_batch_run(args: argparse.Namespace) -> int:
    """Execute batch run command.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code.
    """
    config = BatchConfig(
        target_list_path=Path(args.target_list),
        concurrency=args.concurrency,
        dry_run=args.dry_run,
        max_repos=args.max_repos,
    )
    report = asyncio.run(run_batch(config))

    fmt = getattr(args, "format", "text")
    if fmt == "json":
        print(format_report_json(report))
    else:
        print(format_report_text(report))

    return 0


def cmd_batch_resume(args: argparse.Namespace) -> int:
    """Execute batch resume command.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code.
    """
    report = asyncio.run(resume_batch(Path(args.checkpoint)))

    fmt = getattr(args, "format", "text")
    if fmt == "json":
        print(format_report_json(report))
    else:
        print(format_report_text(report))

    return 0


def cmd_batch_status(args: argparse.Namespace) -> int:
    """Display batch status from checkpoint.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code.
    """
    state = _load_checkpoint(Path(args.checkpoint))

    completed = sum(1 for t in state.tasks if t.status == TaskStatus.COMPLETED)
    failed = sum(1 for t in state.tasks if t.status == TaskStatus.FAILED)
    pending = sum(1 for t in state.tasks if t.status == TaskStatus.PENDING)
    total = len(state.tasks)

    print(f"Batch: {state.batch_id}")
    print(f"Status: {completed}/{total} completed, {failed} failed, {pending} pending")
    return 0


def cmd_batch_cleanup(args: argparse.Namespace) -> int:
    """Execute cleanup command.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code.
    """
    clone_dir = Path(args.clone_dir)
    usage, over = check_disk_usage(clone_dir, float("inf"))
    print(f"Clone directory: {clone_dir}")
    print(f"Disk usage: {usage:.2f} GB")

    if over:
        print("WARNING: Over configured limit")

    return 0
