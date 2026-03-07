"""Data models for Repo Scout.

See LLD #3 §2.3 for model specification.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import TypedDict


class DiscoverySource(Enum):
    """How a repository was discovered."""

    AWESOME_LIST = "awesome_list"
    STARRED_REPO = "starred_repo"
    LLM_SUGGESTION = "llm_suggestion"
    STARGAZER_TARGET = "stargazer_target"


class RepositoryRecord(TypedDict):
    """A discovered GitHub repository."""

    owner: str
    name: str
    full_name: str
    url: str
    description: str | None
    stars: int | None
    sources: list[str]  # DiscoverySource values
    discovered_at: str  # ISO 8601
    metadata: dict


class ScoutConfig(TypedDict, total=False):
    """Configuration for a scout run."""

    github_token: str
    llm_api_key: str | None
    max_star_depth: int
    rate_limit_delay: float
    output_path: str
    output_format: str


def make_repo_record(
    owner: str,
    name: str,
    source: DiscoverySource,
    description: str | None = None,
    stars: int | None = None,
    metadata: dict | None = None,
) -> RepositoryRecord:
    """Create a RepositoryRecord with defaults.

    Args:
        owner: GitHub owner/org.
        name: Repository name.
        source: How the repo was discovered.
        description: Repo description.
        stars: Star count.
        metadata: Extra source-specific data.

    Returns:
        Populated RepositoryRecord.
    """
    return RepositoryRecord(
        owner=owner,
        name=name,
        full_name=f"{owner}/{name}",
        url=f"https://github.com/{owner}/{name}",
        description=description,
        stars=stars,
        sources=[source.value],
        discovered_at=datetime.now(timezone.utc).isoformat(),
        metadata=metadata or {},
    )
