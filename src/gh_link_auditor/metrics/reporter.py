"""Report generation for batch runs and campaign metrics.

See LLD-019 §2.4 for reporter specification.
"""

from __future__ import annotations

import json
from pathlib import Path

from gh_link_auditor.batch.models import BatchState, TaskStatus, now_utc
from gh_link_auditor.metrics.collector import MetricsCollector
from gh_link_auditor.metrics.models import CampaignMetrics, RunReport


def generate_run_report(state: BatchState) -> RunReport:
    """Generate a RunReport from completed batch state.

    Args:
        state: Completed or partially completed BatchState.

    Returns:
        RunReport with aggregated counters.
    """
    completed_at = now_utc()
    started_at = state.started_at or completed_at

    repos_succeeded = sum(
        1 for t in state.tasks if t.status == TaskStatus.COMPLETED
    )
    repos_failed = sum(
        1 for t in state.tasks if t.status == TaskStatus.FAILED
    )
    repos_skipped = sum(
        1 for t in state.tasks if t.status == TaskStatus.SKIPPED
    )

    errors = []
    for t in state.tasks:
        if t.status == TaskStatus.FAILED and t.error_message:
            errors.append(
                {"repo": t.repo_full_name, "error_message": t.error_message}
            )

    duration = (completed_at - started_at).total_seconds()

    return RunReport(
        batch_id=state.batch_id,
        started_at=started_at,
        completed_at=completed_at,
        repos_scanned=len(state.tasks),
        repos_succeeded=repos_succeeded,
        repos_failed=repos_failed,
        repos_skipped=repos_skipped,
        total_links_found=sum(t.links_found for t in state.tasks),
        total_broken_links=sum(t.broken_links for t in state.tasks),
        total_fixes_generated=sum(t.fixes_generated for t in state.tasks),
        total_prs_submitted=sum(1 for t in state.tasks if t.pr_submitted),
        duration_seconds=duration,
        errors=errors,
    )


def generate_campaign_metrics(db_path: Path) -> CampaignMetrics:
    """Aggregate metrics across all batch runs in the database.

    Args:
        db_path: Path to metrics SQLite database.

    Returns:
        CampaignMetrics with aggregated values.
    """
    collector = MetricsCollector(db_path)
    try:
        runs = collector.get_all_runs()
        outcomes = collector.get_all_pr_outcomes()
    finally:
        collector.close()

    total_repos = sum(r.repos_scanned for r in runs)
    total_prs = sum(r.total_prs_submitted for r in runs)

    merged = sum(1 for o in outcomes if o.status == "merged")
    rejected = sum(1 for o in outcomes if o.status in ("closed", "rejected"))
    open_prs = sum(1 for o in outcomes if o.status == "open")

    denominator = merged + rejected
    acceptance_rate = merged / denominator if denominator > 0 else 0.0

    merge_times = [
        o.time_to_merge_hours
        for o in outcomes
        if o.time_to_merge_hours is not None
    ]
    avg_ttm = sum(merge_times) / len(merge_times) if merge_times else 0.0

    rejection_reasons: dict[str, int] = {}
    for o in outcomes:
        if o.status in ("closed", "rejected") and o.rejection_reason:
            reason = o.rejection_reason
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1

    return CampaignMetrics(
        total_runs=len(runs),
        total_repos_processed=total_repos,
        total_prs_submitted=total_prs,
        total_prs_merged=merged,
        total_prs_rejected=rejected,
        total_prs_open=open_prs,
        acceptance_rate=acceptance_rate,
        avg_time_to_merge_hours=avg_ttm,
        rejection_reasons=rejection_reasons,
    )


def format_report_text(report: RunReport) -> str:
    """Format a RunReport as human-readable text.

    Args:
        report: RunReport to format.

    Returns:
        Multi-line text string.
    """
    lines = [
        f"Batch Run Report: {report.batch_id}",
        f"Started:    {report.started_at.isoformat()}",
        f"Completed:  {report.completed_at.isoformat()}",
        f"Duration:   {report.duration_seconds:.1f}s",
        "",
        f"Repos scanned:      {report.repos_scanned}",
        f"Repos succeeded:    {report.repos_succeeded}",
        f"Repos failed:       {report.repos_failed}",
        f"Repos skipped:      {report.repos_skipped}",
        "",
        f"Links found:        {report.total_links_found}",
        f"Broken links:       {report.total_broken_links}",
        f"Fixes generated:    {report.total_fixes_generated}",
        f"PRs submitted:      {report.total_prs_submitted}",
    ]

    if report.errors:
        lines.append("")
        lines.append("Errors:")
        for err in report.errors:
            lines.append(f"  {err['repo']}: {err['error_message']}")

    return "\n".join(lines)


def format_report_json(report: RunReport) -> str:
    """Format a RunReport as JSON string.

    Args:
        report: RunReport to format.

    Returns:
        JSON string.
    """
    data = {
        "batch_id": report.batch_id,
        "started_at": report.started_at.isoformat(),
        "completed_at": report.completed_at.isoformat(),
        "duration_seconds": report.duration_seconds,
        "repos_scanned": report.repos_scanned,
        "repos_succeeded": report.repos_succeeded,
        "repos_failed": report.repos_failed,
        "repos_skipped": report.repos_skipped,
        "total_links_found": report.total_links_found,
        "total_broken_links": report.total_broken_links,
        "total_fixes_generated": report.total_fixes_generated,
        "total_prs_submitted": report.total_prs_submitted,
        "errors": report.errors,
    }
    return json.dumps(data, indent=2)


def format_campaign_text(metrics: CampaignMetrics) -> str:
    """Format CampaignMetrics as human-readable text.

    Args:
        metrics: CampaignMetrics to format.

    Returns:
        Multi-line text string.
    """
    lines = [
        "Campaign Metrics",
        f"Total runs:             {metrics.total_runs}",
        f"Total repos processed:  {metrics.total_repos_processed}",
        f"Total PRs submitted:    {metrics.total_prs_submitted}",
        f"  Merged:               {metrics.total_prs_merged}",
        f"  Rejected:             {metrics.total_prs_rejected}",
        f"  Open:                 {metrics.total_prs_open}",
        f"Acceptance rate:        {metrics.acceptance_rate:.1%}",
        f"Avg time to merge:      {metrics.avg_time_to_merge_hours:.1f}h",
    ]

    if metrics.rejection_reasons:
        lines.append("")
        lines.append("Rejection reasons:")
        for reason, count in sorted(
            metrics.rejection_reasons.items(), key=lambda x: -x[1]
        ):
            lines.append(f"  {reason}: {count}")

    return "\n".join(lines)
