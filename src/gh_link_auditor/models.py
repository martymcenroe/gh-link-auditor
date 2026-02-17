"""Pydantic models for database entities.

Defines InteractionRecord, BlacklistEntry, and InteractionStatus
for the state database. See LLD Issue #5 for full specification.
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
