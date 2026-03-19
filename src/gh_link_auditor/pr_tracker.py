"""PR outcome tracker — polls GitHub API to refresh PR status.

Reads open PRs from the metrics database, checks their current status
via the GitHub API, and updates the database.

See Issue #86 for specification.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gh_link_auditor.metrics.models import PROutcome

logger = logging.getLogger(__name__)


def _parse_pr_url(pr_url: str) -> tuple[str, str, int]:
    """Parse owner, repo, and PR number from a GitHub PR URL.

    Args:
        pr_url: URL like "https://github.com/owner/repo/pull/123".

    Returns:
        Tuple of (owner, repo, pr_number).

    Raises:
        ValueError: If URL cannot be parsed.
    """
    parts = pr_url.rstrip("/").split("/")
    # Expected: [..., "github.com", owner, repo, "pull", number]
    try:
        pull_idx = parts.index("pull")
        owner = parts[pull_idx - 2]
        repo = parts[pull_idx - 1]
        number = int(parts[pull_idx + 1])
        return (owner, repo, number)
    except (ValueError, IndexError) as exc:
        msg = f"Cannot parse PR URL: {pr_url}"
        raise ValueError(msg) from exc


def _fetch_pr_status(owner: str, repo: str, pr_number: int) -> dict:
    """Fetch PR status from GitHub API via gh CLI.

    Args:
        owner: Repository owner.
        repo: Repository name.
        pr_number: PR number.

    Returns:
        Dict with keys: state, merged, merged_at, closed_at.

    Raises:
        RuntimeError: If the API call fails.
    """
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{owner}/{repo}/pulls/{pr_number}",
                "--jq",
                "{state: .state, merged: .merged, merged_at: .merged_at, closed_at: .closed_at}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            msg = f"gh api failed for {owner}/{repo}#{pr_number}: {result.stderr.strip()}"
            raise RuntimeError(msg)

        import json

        return json.loads(result.stdout)

    except FileNotFoundError as exc:
        msg = "gh CLI not found"
        raise RuntimeError(msg) from exc


def _check_maintainer_fixed(
    owner: str,
    repo: str,
    pr_number: int,
) -> bool:
    """Check if the maintainer committed the same fix after closing our PR.

    Looks at commits after the PR was closed for similar URL changes.

    Args:
        owner: Repository owner.
        repo: Repository name.
        pr_number: PR number (closed).

    Returns:
        True if evidence suggests maintainer fixed it themselves.
    """
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{owner}/{repo}/pulls/{pr_number}",
                "--jq",
                ".body",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return False

        # Check recent commits on default branch for similar file changes
        commits_result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{owner}/{repo}/commits",
                "--jq",
                ".[0:5] | .[].commit.message",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if commits_result.returncode != 0:
            return False

        # Heuristic: if recent commits mention "fix", "link", "url", or "broken"
        # in the same area, the maintainer likely fixed it themselves
        messages = commits_result.stdout.lower()
        keywords = ["fix", "link", "url", "broken", "dead", "redirect"]
        return any(kw in messages for kw in keywords)

    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def refresh_pr_outcomes(db_path: Path) -> list[PROutcome]:
    """Poll GitHub API for all open PRs and update their status.

    Args:
        db_path: Path to metrics SQLite database.

    Returns:
        List of PROutcome objects that were updated.
    """
    from gh_link_auditor.metrics.collector import MetricsCollector

    collector = MetricsCollector(db_path)
    try:
        all_outcomes = collector.get_all_pr_outcomes()
        open_prs = [o for o in all_outcomes if o.status == "open"]

        if not open_prs:
            logger.info("No open PRs to refresh")
            return []

        updated: list[PROutcome] = []

        for outcome in open_prs:
            try:
                owner, repo, pr_number = _parse_pr_url(outcome.pr_url)
            except ValueError:
                logger.warning("Skipping unparseable PR URL: %s", outcome.pr_url)
                continue

            try:
                api_data = _fetch_pr_status(owner, repo, pr_number)
            except RuntimeError:
                logger.warning("Failed to fetch status for %s", outcome.pr_url)
                continue

            new_status = _determine_status(api_data)
            if new_status == outcome.status:
                continue

            # Update the outcome
            now = datetime.now(timezone.utc)

            if new_status == "merged":
                merged_at = _parse_iso_datetime(api_data.get("merged_at"))
                ttm = None
                if merged_at:
                    ttm = (merged_at - outcome.submitted_at).total_seconds() / 3600.0
                outcome.status = "merged"
                outcome.merged_at = merged_at or now
                outcome.time_to_merge_hours = ttm

            elif new_status == "closed":
                closed_at = _parse_iso_datetime(api_data.get("closed_at"))
                outcome.status = "closed"
                outcome.closed_at = closed_at or now

                # Check if maintainer fixed it themselves
                maintainer_fixed = _check_maintainer_fixed(owner, repo, pr_number)
                if maintainer_fixed:
                    outcome.rejection_reason = "maintainer committed fix directly"

            collector.record_pr_outcome(outcome)
            updated.append(outcome)
            logger.info(
                "Updated %s: %s → %s",
                outcome.pr_url,
                "open",
                new_status,
            )

        return updated

    finally:
        collector.close()


def _determine_status(api_data: dict) -> str:
    """Determine PR status from API response.

    Args:
        api_data: Dict with state, merged, merged_at, closed_at.

    Returns:
        Status string: "open", "merged", or "closed".
    """
    if api_data.get("merged"):
        return "merged"
    state = api_data.get("state", "open")
    if state == "closed":
        return "closed"
    return "open"


def _parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string, returning None on failure.

    Args:
        value: ISO datetime string or None.

    Returns:
        Parsed datetime or None.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
