"""Campaign dashboard — terminal display of contribution stats.

Formats campaign metrics and recent PR outcomes into a human-readable
terminal dashboard.

See Issue #87 for specification.
"""

from __future__ import annotations

from datetime import datetime, timezone

from gh_link_auditor.metrics.models import CampaignMetrics, PROutcome


def format_dashboard(
    metrics: CampaignMetrics,
    recent_prs: list[PROutcome],
    now: datetime | None = None,
) -> str:
    """Format the full campaign dashboard.

    Args:
        metrics: Aggregate campaign metrics.
        recent_prs: List of recent PR outcomes (sorted newest first).
        now: Current time (defaults to UTC now, injectable for testing).

    Returns:
        Multi-line formatted dashboard string.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    lines: list[str] = []

    # Header
    lines.append("Campaign Summary")
    lines.append("=" * 40)

    # Aggregate stats
    lines.append(f"Repos scanned:    {metrics.total_repos_processed:>5}")

    total_prs = metrics.total_prs_submitted
    lines.append(f"PRs submitted:    {total_prs:>5}")

    # Merged with percentage
    merged_pct = _pct(metrics.total_prs_merged, total_prs)
    lines.append(f"PRs merged:       {metrics.total_prs_merged:>5}  ({merged_pct})")

    # Closed with annotation
    closed = metrics.total_prs_rejected
    closed_pct = _pct(closed, total_prs)
    lines.append(f"PRs closed:       {closed:>5}  ({closed_pct})")

    # Open
    open_prs = metrics.total_prs_open
    open_pct = _pct(open_prs, total_prs)
    lines.append(f"PRs open:         {open_prs:>5}  ({open_pct})")

    # Acceptance rate
    lines.append(f"Acceptance rate:  {metrics.acceptance_rate:>5.1%}")

    # Avg time to merge
    if metrics.avg_time_to_merge_hours > 0:
        lines.append(f"Avg time to merge: {_format_duration(metrics.avg_time_to_merge_hours)}")

    # Rejection reasons
    if metrics.rejection_reasons:
        lines.append("")
        lines.append("Rejection reasons:")
        for reason, count in sorted(metrics.rejection_reasons.items(), key=lambda x: -x[1]):
            lines.append(f"  {reason}: {count}")

    # Recent PRs
    if recent_prs:
        lines.append("")
        lines.append("Recent PRs:")
        for pr in recent_prs[:10]:  # Show at most 10
            line = _format_pr_line(pr, now)
            lines.append(f"  {line}")

    return "\n".join(lines)


def _pct(part: int, total: int) -> str:
    """Format a percentage string.

    Args:
        part: Numerator.
        total: Denominator.

    Returns:
        Formatted string like "62.5%" or "0.0%".
    """
    if total == 0:
        return "0.0%"
    return f"{part / total * 100:.1f}%"


def _format_duration(hours: float) -> str:
    """Format hours into a human-readable duration.

    Args:
        hours: Duration in hours.

    Returns:
        Formatted string like "2d 5h" or "3h".
    """
    if hours >= 24:
        days = int(hours // 24)
        remaining_hours = int(hours % 24)
        if remaining_hours > 0:
            return f"{days}d {remaining_hours}h"
        return f"{days}d"
    return f"{hours:.0f}h"


def _format_pr_line(pr: PROutcome, now: datetime) -> str:
    """Format a single PR outcome as a dashboard line.

    Args:
        pr: PR outcome to format.
        now: Current time for relative timestamp.

    Returns:
        Formatted string like "pallets/flask #123  MERGED  2d ago".
    """
    repo = pr.repo_full_name
    # Extract PR number from URL
    pr_number = _extract_number(pr.pr_url)
    number_str = f"#{pr_number}" if pr_number else ""

    status = pr.status.upper()
    age = _relative_time(pr.submitted_at, now)

    # Build the line
    repo_part = f"{repo} {number_str}".ljust(35)
    status_part = status.ljust(8)

    line = f"{repo_part} {status_part} {age}"

    # Add annotation for closed PRs
    if pr.status == "closed" and pr.rejection_reason:
        line += f"  ({pr.rejection_reason})"

    return line


def _extract_number(pr_url: str) -> int:
    """Extract PR number from URL.

    Args:
        pr_url: GitHub PR URL.

    Returns:
        PR number, or 0 if parsing fails.
    """
    try:
        parts = pr_url.rstrip("/").split("/")
        return int(parts[-1])
    except (ValueError, IndexError):
        return 0


def _relative_time(dt: datetime, now: datetime) -> str:
    """Format a datetime as relative time (e.g., "2d ago").

    Args:
        dt: The datetime to format.
        now: Current time.

    Returns:
        Relative time string.
    """
    delta = now - dt
    total_seconds = delta.total_seconds()

    if total_seconds < 0:
        return "just now"
    if total_seconds < 60:
        return "just now"
    if total_seconds < 3600:
        minutes = int(total_seconds // 60)
        return f"{minutes}m ago"
    if total_seconds < 86400:
        hours = int(total_seconds // 3600)
        return f"{hours}h ago"
    days = int(total_seconds // 86400)
    return f"{days}d ago"


def format_dashboard_json(
    metrics: CampaignMetrics,
    recent_prs: list[PROutcome],
) -> dict:
    """Format dashboard data as a JSON-serializable dict.

    Args:
        metrics: Aggregate campaign metrics.
        recent_prs: List of recent PR outcomes.

    Returns:
        Dictionary suitable for JSON serialization.
    """
    return {
        "total_runs": metrics.total_runs,
        "total_repos_processed": metrics.total_repos_processed,
        "total_prs_submitted": metrics.total_prs_submitted,
        "total_prs_merged": metrics.total_prs_merged,
        "total_prs_rejected": metrics.total_prs_rejected,
        "total_prs_open": metrics.total_prs_open,
        "acceptance_rate": metrics.acceptance_rate,
        "avg_time_to_merge_hours": metrics.avg_time_to_merge_hours,
        "rejection_reasons": metrics.rejection_reasons,
        "recent_prs": [
            {
                "repo": pr.repo_full_name,
                "pr_url": pr.pr_url,
                "status": pr.status,
                "submitted_at": pr.submitted_at.isoformat(),
                "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
                "closed_at": pr.closed_at.isoformat() if pr.closed_at else None,
                "rejection_reason": pr.rejection_reason,
                "time_to_merge_hours": pr.time_to_merge_hours,
            }
            for pr in recent_prs
        ],
    }
