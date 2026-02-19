"""Data models for Doc-Fix Bot.

See LLD #2 §2.3 for model specification.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, TypedDict


class TargetRepository(TypedDict):
    """A repository to scan for broken links."""

    owner: str
    repo: str
    priority: int
    last_scanned: str | None  # ISO 8601
    enabled: bool


class BrokenLink(TypedDict):
    """A broken link found during scanning."""

    source_file: str
    line_number: int
    original_url: str
    status_code: int
    suggested_fix: str | None
    fix_confidence: float


class ScanResult(TypedDict):
    """Result of scanning a single repository."""

    repository: TargetRepository
    scan_time: str  # ISO 8601
    broken_links: list[BrokenLink]
    error: str | None
    files_scanned: int
    links_checked: int


class PRSubmission(TypedDict):
    """A submitted pull request."""

    repository: TargetRepository
    branch_name: str
    pr_number: int | None
    pr_url: str | None
    status: Literal["pending", "submitted", "merged", "closed", "rejected"]
    broken_links_fixed: list[BrokenLink]
    submitted_at: str  # ISO 8601


class BotState(TypedDict):
    """Overall bot state."""

    last_run: str  # ISO 8601
    total_prs_submitted: int
    total_links_fixed: int


class URLValidationResult(TypedDict):
    """Result of SSRF URL validation."""

    url: str
    is_safe: bool
    resolved_ip: str | None
    rejection_reason: str | None


class BotConfig(TypedDict, total=False):
    """Bot configuration."""

    github_token: str
    user_agent: str
    http_timeout: float
    max_prs_per_day: int
    max_api_calls_per_hour: int
    min_fix_confidence: float
    targets_path: str
    blocklist_path: str
    state_db_path: str


def make_target(
    owner: str,
    repo: str,
    priority: int = 5,
    enabled: bool = True,
) -> TargetRepository:
    """Create a TargetRepository with defaults.

    Args:
        owner: GitHub owner/org.
        repo: Repository name.
        priority: Scan priority (1-10, higher first).
        enabled: Whether to scan this repo.

    Returns:
        Populated TargetRepository.
    """
    return TargetRepository(
        owner=owner,
        repo=repo,
        priority=priority,
        last_scanned=None,
        enabled=enabled,
    )


def make_broken_link(
    source_file: str,
    line_number: int,
    original_url: str,
    status_code: int,
    suggested_fix: str | None = None,
    fix_confidence: float = 0.0,
) -> BrokenLink:
    """Create a BrokenLink.

    Args:
        source_file: File containing the link.
        line_number: Line where link appears.
        original_url: The broken URL.
        status_code: HTTP status code.
        suggested_fix: Suggested replacement URL.
        fix_confidence: Confidence in the fix (0.0-1.0).

    Returns:
        Populated BrokenLink.
    """
    return BrokenLink(
        source_file=source_file,
        line_number=line_number,
        original_url=original_url,
        status_code=status_code,
        suggested_fix=suggested_fix,
        fix_confidence=fix_confidence,
    )


def now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()
