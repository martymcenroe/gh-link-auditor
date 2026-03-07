"""Post-PR branch/fork/clone cleanup and storage management.

See LLD-019 §2.4 for cleanup specification.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


async def cleanup_clone(clone_path: Path) -> None:
    """Delete a local clone directory.

    Args:
        clone_path: Path to the clone directory.
    """
    if clone_path.exists():
        shutil.rmtree(clone_path, ignore_errors=True)


async def cleanup_remote_branch(repo_full_name: str, branch_name: str, token: str) -> bool:
    """Delete a remote branch via GitHub API after PR merge/close.

    Args:
        repo_full_name: Owner/repo string.
        branch_name: Branch to delete.
        token: GitHub token.

    Returns:
        True if branch was deleted, False otherwise.
    """
    url = f"https://api.github.com/repos/{repo_full_name}/git/refs/heads/{branch_name}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, headers=headers, timeout=10.0)
        return resp.status_code == 204
    except httpx.HTTPError:
        logger.exception("Failed to delete branch %s on %s", branch_name, repo_full_name)
        return False


async def prune_stale_forks(forks: list[dict], token: str, max_age_days: int = 90) -> list[str]:
    """Identify forks that are stale (PRs merged/rejected and older than threshold).

    Args:
        forks: List of fork dicts with 'full_name', 'created_at', 'pr_status' keys.
        token: GitHub token.
        max_age_days: Age threshold in days.

    Returns:
        List of full names of forks identified as stale.
    """
    now = datetime.now(timezone.utc)
    stale: list[str] = []

    for fork in forks:
        created_str = fork.get("created_at", "")
        pr_status = fork.get("pr_status", "open")

        if pr_status == "open":
            continue

        if created_str:
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            age_days = (now - created).days
            if age_days >= max_age_days:
                stale.append(fork["full_name"])

    return stale


def check_disk_usage(clone_dir: Path, max_gb: float) -> tuple[float, bool]:
    """Return current disk usage and whether it exceeds the limit.

    Args:
        clone_dir: Directory to check.
        max_gb: Maximum allowed size in GB.

    Returns:
        Tuple of (current_usage_gb, is_over_limit).
    """
    if not clone_dir.exists():
        return (0.0, False)

    total_bytes = sum(f.stat().st_size for f in clone_dir.rglob("*") if f.is_file())
    usage_gb = total_bytes / (1024**3)
    return (round(usage_gb, 6), usage_gb > max_gb)
