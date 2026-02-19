"""Star Walker — Traverse GitHub starred repos graph.

See LLD #3 §2.4 for star_walker specification.
Deviation: synchronous (not async) to match codebase conventions.
"""

from __future__ import annotations

import logging

from repo_scout.github_client import GitHubClient
from repo_scout.models import RepositoryRecord

logger = logging.getLogger(__name__)


def get_user_starred(
    username: str,
    github_client: GitHubClient,
) -> list[RepositoryRecord]:
    """Get all starred repos for a single user.

    Args:
        username: GitHub username.
        github_client: Configured GitHub client.

    Returns:
        List of starred RepositoryRecords.
    """
    return github_client.get_starred(username)


def walk_starred_repos(
    root_user: str,
    github_client: GitHubClient,
    max_depth: int = 2,
    visited: set[str] | None = None,
) -> list[RepositoryRecord]:
    """Traverse starred repos graph up to max_depth.

    BFS traversal. At each level, gets starred repos of users
    who own repos starred at the previous level.

    Args:
        root_user: Starting GitHub username.
        github_client: Configured GitHub client.
        max_depth: Maximum traversal depth.
        visited: Set of already-visited repos (for cycle detection).

    Returns:
        All discovered RepositoryRecords.
    """
    if visited is None:
        visited = set()

    all_records: list[RepositoryRecord] = []
    current_users = [root_user]

    for depth in range(max_depth):
        next_users: set[str] = set()

        for username in current_users:
            logger.info("Walking stars for %s (depth %d)", username, depth)
            starred = get_user_starred(username, github_client)

            for record in starred:
                full_name = record["full_name"]
                if full_name in visited:
                    continue
                visited.add(full_name)

                record["metadata"]["root_user"] = root_user
                record["metadata"]["depth"] = depth
                all_records.append(record)

                # Add repo owner as candidate for next depth
                next_users.add(record["owner"])

        current_users = list(next_users - {root_user})

    return all_records
