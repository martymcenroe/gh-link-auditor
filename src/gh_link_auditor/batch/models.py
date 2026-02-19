"""Data structures for batch execution engine.

See LLD-019 §2.3 for model specification.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TypedDict

from gh_link_auditor.batch.exceptions import BatchInputError

# Repo name validation: owner/name with alphanumeric, dots, hyphens, underscores
REPO_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$")


class TaskStatus(Enum):
    """Status of a single repo task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class BatchConfig:
    """Configuration for a batch execution run."""

    target_list_path: Path
    concurrency: int = 1
    max_repos: int | None = None
    dry_run: bool = False
    checkpoint_interval: int = 10
    clone_dir: Path = field(default_factory=lambda: Path("/tmp/batch_clones"))
    max_disk_gb: float = 10.0
    token_file: Path | None = None
    resume_from: Path | None = None


@dataclass
class TokenState:
    """Tracks rate limit state for a single GitHub token."""

    token: str
    remaining: int = 5000
    reset_at: datetime | None = None
    scopes: list[str] = field(default_factory=list)
    is_valid: bool = True

    def __repr__(self) -> str:
        suffix = self.token[-4:] if len(self.token) >= 4 else "****"
        return f"TokenState(token=...{suffix}, remaining={self.remaining}, valid={self.is_valid})"


@dataclass
class RepoTask:
    """A single repo to process in the batch."""

    repo_full_name: str
    clone_url: str
    status: TaskStatus = TaskStatus.PENDING
    error_message: str | None = None
    links_found: int = 0
    broken_links: int = 0
    fixes_generated: int = 0
    pr_submitted: bool = False
    pr_url: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class RateLimitSnapshot(TypedDict):
    """Point-in-time rate limit state across all tokens."""

    total_remaining: int
    lowest_remaining: int
    next_reset: str
    backpressure_active: bool


@dataclass
class BatchState:
    """Serializable batch state for resumability."""

    batch_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    config: BatchConfig | None = None
    tasks: list[RepoTask] = field(default_factory=list)
    current_index: int = 0
    started_at: datetime | None = None
    last_checkpoint_at: datetime | None = None
    total_api_calls: int = 0


def validate_repo_name(name: str) -> None:
    """Validate a repository full name (owner/repo).

    Args:
        name: Repository full name.

    Raises:
        BatchInputError: If name is invalid.
    """
    if not REPO_NAME_PATTERN.match(name):
        msg = f"Invalid repository name: {name!r}"
        raise BatchInputError(msg)


def now_utc() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)
