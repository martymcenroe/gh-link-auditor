"""Stargazer-targeted repository discovery.

Harvests repos maintained by users who starred given seed repositories.
See LLD #36 for specification.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from repo_scout.github_client import GitHubClient
from repo_scout.models import RepositoryRecord

logger = logging.getLogger(__name__)


def _is_recently_active(pushed_at: str | None, max_age_months: int) -> bool:
    """Check if a repo was pushed to within the age threshold.

    Args:
        pushed_at: ISO 8601 timestamp of last push, or None.
        max_age_months: Maximum age in months.

    Returns:
        True if the repo is recently active.
    """
    if pushed_at is None:
        return False
    try:
        push_dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta_days = (now - push_dt).days
        return delta_days <= max_age_months * 30
    except (ValueError, TypeError):
        return False


def harvest_from_stargazers(
    seed_repos: list[str],
    github_client: GitHubClient,
    max_stargazers: int = 100,
    max_repo_age_months: int = 6,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> list[RepositoryRecord]:
    """Discover repos by harvesting stargazer-owned repositories.

    Args:
        seed_repos: Repos whose stargazers to harvest (owner/repo format).
        github_client: Authenticated GitHub client.
        max_stargazers: Max stargazers to fetch per seed repo.
        max_repo_age_months: Only include repos active within N months.
        progress_callback: Optional (message, current, total) callback.

    Returns:
        List of discovered RepositoryRecords.
    """
    all_repos: list[RepositoryRecord] = []
    visited_users: set[str] = set()

    for seed_idx, seed in enumerate(seed_repos):
        parts = seed.split("/")
        if len(parts) != 2:
            logger.warning("Invalid seed repo format: %s", seed)
            continue

        owner, repo = parts
        stargazers = github_client.get_stargazers(owner, repo, max_count=max_stargazers)

        for user_idx, username in enumerate(stargazers):
            if username in visited_users:
                continue
            visited_users.add(username)

            if progress_callback:
                progress_callback(
                    f"Fetching repos for {username} (seed: {seed})",
                    user_idx + 1,
                    len(stargazers),
                )

            user_repos = github_client.get_user_repos(username)
            for user_repo in user_repos:
                pushed_at = user_repo["metadata"].get("pushed_at")
                if not _is_recently_active(pushed_at, max_repo_age_months):
                    continue
                user_repo["metadata"]["seed_repo"] = seed
                user_repo["metadata"]["stargazer_username"] = username
                all_repos.append(user_repo)

    return all_repos
