"""LLM-powered repo suggestion generator.

See LLD #3 §2.4 for llm_brainstormer specification.
Deviation: synchronous, optional (gated by env var), no LLM library dependency.
"""

from __future__ import annotations

import logging
import re

from repo_scout.github_client import GitHubClient
from repo_scout.models import DiscoverySource, RepositoryRecord, make_repo_record

logger = logging.getLogger(__name__)


def build_suggestion_prompt(
    keywords: list[str],
    existing_repos: list[str],
) -> str:
    """Build a prompt for LLM repo suggestions.

    Args:
        keywords: Keywords describing the kind of repos to find.
        existing_repos: Already-known repos to avoid duplicates.

    Returns:
        Formatted prompt string.
    """
    existing_str = "\n".join(f"- {r}" for r in existing_repos[:20])
    keywords_str = ", ".join(keywords)

    return (
        f"Suggest GitHub repositories related to: {keywords_str}\n\n"
        f"Already known repositories (do not repeat these):\n{existing_str}\n\n"
        "Please respond with a list of GitHub repositories in owner/repo format, "
        "one per line. Only include real, existing repositories."
    )


def parse_llm_response(response: str) -> list[str]:
    """Parse LLM response for repository suggestions.

    Extracts owner/repo patterns from the response text.

    Args:
        response: Raw LLM response text.

    Returns:
        List of "owner/repo" strings.
    """
    # Match owner/repo patterns (allowing hyphens, underscores, dots)
    pattern = re.compile(r"([A-Za-z0-9\-_.]+/[A-Za-z0-9\-_.]+)")
    matches = pattern.findall(response)

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for match in matches:
        if match not in seen:
            seen.add(match)
            result.append(match)

    return result


def validate_suggestions(
    suggestions: list[str],
    github_client: GitHubClient,
) -> list[RepositoryRecord]:
    """Validate that suggested repos actually exist on GitHub.

    Args:
        suggestions: List of "owner/repo" strings.
        github_client: Configured GitHub client.

    Returns:
        List of validated RepositoryRecords.
    """
    records: list[RepositoryRecord] = []
    for suggestion in suggestions:
        parts = suggestion.split("/")
        if len(parts) != 2:
            continue

        owner, name = parts
        if github_client.repo_exists(suggestion):
            records.append(
                make_repo_record(
                    owner=owner,
                    name=name,
                    source=DiscoverySource.LLM_SUGGESTION,
                    metadata={"suggestion": suggestion},
                )
            )
        else:
            logger.info("Repo does not exist: %s", suggestion)

    return records


def suggest_repos(
    keywords: list[str],
    existing_repos: list[str],
    llm_response: str | None = None,
    github_client: GitHubClient | None = None,
) -> list[RepositoryRecord]:
    """Generate and validate LLM repo suggestions.

    If llm_response is provided, uses it directly instead of calling an LLM.
    This enables testing without an actual LLM API.

    Args:
        keywords: Keywords for discovery.
        existing_repos: Already-known repos.
        llm_response: Pre-computed LLM response (for testing).
        github_client: GitHub client for validation.

    Returns:
        List of validated RepositoryRecords.
    """
    if llm_response is None:
        logger.warning("No LLM response provided — LLM brainstorming disabled")
        return []

    suggestions = parse_llm_response(llm_response)
    if not suggestions:
        return []

    if github_client is None:
        # Without GitHub client, return unvalidated records
        return [
            make_repo_record(
                owner=s.split("/")[0],
                name=s.split("/")[1],
                source=DiscoverySource.LLM_SUGGESTION,
                metadata={"suggestion": s, "validated": False},
            )
            for s in suggestions
            if "/" in s
        ]

    return validate_suggestions(suggestions, github_client)
