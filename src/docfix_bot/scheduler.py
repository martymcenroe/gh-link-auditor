"""Daily scan orchestration.

See LLD #2 §2.4 for scheduler specification.
Deviation: synchronous to match codebase conventions.
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from docfix_bot.config import get_default_config
from docfix_bot.git_workflow import clone_repository, execute_fix_workflow
from docfix_bot.link_scanner import scan_repository
from docfix_bot.models import BotConfig, PRSubmission, ScanResult, now_iso
from docfix_bot.pr_generator import generate_pr_body, generate_pr_title
from docfix_bot.state_store import StateStore
from docfix_bot.target_manager import (
    check_contributing_md,
    is_blocklisted,
    load_targets,
    prioritize_targets,
)

logger = logging.getLogger(__name__)


def should_continue(state: StateStore, config: BotConfig) -> bool:
    """Check if we've hit daily limits.

    Args:
        state: Current bot state.
        config: Bot configuration.

    Returns:
        True if we can continue scanning.
    """
    max_prs = config.get("max_prs_per_day", 10)
    max_api = config.get("max_api_calls_per_hour", 500)

    daily_count = state.get_daily_pr_count()
    hourly_count = state.get_hourly_api_count()

    if daily_count >= max_prs:
        logger.info("Daily PR limit reached: %d/%d", daily_count, max_prs)
        return False

    if hourly_count >= max_api:
        logger.info("Hourly API limit reached: %d/%d", hourly_count, max_api)
        return False

    return True


def run_daily_scan(
    config: BotConfig | None = None,
    state: StateStore | None = None,
) -> list[PRSubmission]:
    """Main entry point for daily execution.

    Args:
        config: Bot configuration (uses defaults if None).
        state: State store (creates new if None).

    Returns:
        List of PR submissions made.
    """
    if config is None:
        config = get_default_config()

    if state is None:
        db_path = Path(config.get("state_db_path", "data/state/docfix_state.json"))
        state = StateStore(db_path)

    targets_path = Path(config.get("targets_path", "data/config/targets.yaml"))
    blocklist_path = Path(config.get("blocklist_path", "data/config/blocklist.yaml"))

    try:
        targets = load_targets(targets_path)
    except ValueError:
        logger.exception("Failed to load targets")
        return []

    prioritized = prioritize_targets(targets)
    submissions: list[PRSubmission] = []
    scan_results: list[ScanResult] = []

    for target in prioritized:
        if not should_continue(state, config):
            break

        full_name = f"{target['owner']}/{target['repo']}"

        if is_blocklisted(target, blocklist_path):
            logger.info("Skipping blocklisted repo: %s", full_name)
            continue

        if state.was_recently_scanned(target):
            logger.info("Skipping recently scanned: %s", full_name)
            continue

        logger.info("Scanning: %s", full_name)

        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            try:
                repo_dir = clone_repository(target, work_dir)
            except RuntimeError:
                logger.exception("Clone failed for %s", full_name)
                scan_results.append(
                    ScanResult(
                        repository=target,
                        scan_time=now_iso(),
                        broken_links=[],
                        error=f"Clone failed for {full_name}",
                        files_scanned=0,
                        links_checked=0,
                    )
                )
                continue

            # Check CONTRIBUTING.md
            if not check_contributing_md(repo_dir):
                logger.info("Repo %s disallows bot contributions", full_name)
                state.record_scan(target, now_iso())
                continue

            # Scan for broken links
            result = scan_repository(target, config, repo_dir)
            scan_results.append(result)
            state.record_scan(target, now_iso())

            if not result["broken_links"]:
                continue

            # Check for already-fixed links
            new_broken = [
                bl for bl in result["broken_links"]
                if not state.was_link_already_fixed(target, bl["original_url"])
            ]

            if not new_broken:
                continue

            # Generate PR
            fixable = [bl for bl in new_broken if bl["suggested_fix"]]
            if not fixable:
                continue

            pr_title = generate_pr_title(fixable)
            pr_body = generate_pr_body(fixable)

            submission = execute_fix_workflow(
                target, fixable, config, pr_title, pr_body
            )

            if submission["status"] == "submitted":
                state.record_pr_submission(submission)
                submissions.append(submission)

    return submissions


def generate_daily_report(
    scan_results: list[ScanResult],
    submissions: list[PRSubmission],
    output_path: Path,
) -> None:
    """Generate a JSON summary report of the daily scan.

    Args:
        scan_results: List of scan results.
        submissions: List of PR submissions.
        output_path: Path to write report.
    """
    report = {
        "timestamp": now_iso(),
        "repos_scanned": len(scan_results),
        "prs_submitted": len(submissions),
        "total_broken_links": sum(
            len(r["broken_links"]) for r in scan_results
        ),
        "scan_results": scan_results,
        "submissions": submissions,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, default=str))
