"""Pydantic models for database entities.

Defines InteractionRecord, BlacklistEntry, InteractionStatus,
and PipelineRunRecord for the state database.
See LLD Issue #5 and #22 for full specifications.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class InteractionStatus(str, Enum):
    """Status of a bot interaction with a repository."""

    SUBMITTED = "submitted"
    MERGED = "merged"
    DENIED = "denied"
    BLACKLISTED = "blacklisted"


class InteractionRecord(BaseModel):
    """Record of a bot interaction (fix submission) with a repository."""

    id: int
    repo_url: str
    broken_url: str
    status: InteractionStatus
    created_at: datetime
    updated_at: datetime
    pr_url: str | None = None
    maintainer: str | None = None
    notes: str | None = None


class BlacklistEntry(BaseModel):
    """Entry in the maintainer/repo blacklist."""

    id: int
    repo_url: str | None = None
    maintainer: str | None = None
    reason: str = ""
    created_at: datetime
    expires_at: datetime | None = None


class PipelineRunRecord(BaseModel):
    """Record of a pipeline run. See LLD #22 §2.3."""

    run_id: str
    target: str
    started_at: datetime
    completed_at: datetime | None = None
    status: str = "running"  # "running", "completed", "failed", "halted"
    exit_code: int | None = None
    total_cost_usd: float = 0.0
    dead_links_found: int = 0
    fixes_generated: int = 0
