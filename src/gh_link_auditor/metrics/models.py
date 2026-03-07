"""Data structures for metrics and reporting.

See LLD-019 §2.3 for model specification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PROutcome:
    """Tracks the outcome of a submitted PR over time."""

    repo_full_name: str
    pr_url: str
    submitted_at: datetime
    status: str = "open"
    merged_at: datetime | None = None
    closed_at: datetime | None = None
    rejection_reason: str | None = None
    time_to_merge_hours: float | None = None


@dataclass
class RunReport:
    """Summary of a single batch run."""

    batch_id: str
    started_at: datetime
    completed_at: datetime
    repos_scanned: int
    repos_succeeded: int
    repos_failed: int
    repos_skipped: int
    total_links_found: int
    total_broken_links: int
    total_fixes_generated: int
    total_prs_submitted: int
    duration_seconds: float
    errors: list[dict[str, str]] = field(default_factory=list)


@dataclass
class CampaignMetrics:
    """Aggregate metrics across multiple batch runs."""

    total_runs: int
    total_repos_processed: int
    total_prs_submitted: int
    total_prs_merged: int
    total_prs_rejected: int
    total_prs_open: int
    acceptance_rate: float
    avg_time_to_merge_hours: float
    rejection_reasons: dict[str, int] = field(default_factory=dict)
