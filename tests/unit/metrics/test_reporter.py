"""Tests for report generation.

Covers LLD-019 scenarios:
- T180: RunReport generation from BatchState (REQ-10)
- T190: Campaign metrics aggregation (REQ-11)
- T200: Text report formatting (REQ-10)
- T210: JSON report formatting (REQ-10)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from gh_link_auditor.batch.models import BatchState, RepoTask, TaskStatus
from gh_link_auditor.metrics.collector import MetricsCollector
from gh_link_auditor.metrics.models import CampaignMetrics, PROutcome, RunReport
from gh_link_auditor.metrics.reporter import (
    format_campaign_text,
    format_report_json,
    format_report_text,
    generate_campaign_metrics,
    generate_run_report,
)


class TestGenerateRunReport:
    """T180: RunReport generation from BatchState (REQ-10)."""

    def test_all_counters_correct(self) -> None:
        state = BatchState(
            batch_id="report-test",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            tasks=[
                RepoTask(
                    repo_full_name="a/1",
                    clone_url="x",
                    status=TaskStatus.COMPLETED,
                    links_found=10,
                    broken_links=3,
                    fixes_generated=2,
                    pr_submitted=True,
                ),
                RepoTask(
                    repo_full_name="a/2",
                    clone_url="x",
                    status=TaskStatus.COMPLETED,
                    links_found=5,
                    broken_links=1,
                    fixes_generated=1,
                    pr_submitted=False,
                ),
                RepoTask(
                    repo_full_name="a/3",
                    clone_url="x",
                    status=TaskStatus.FAILED,
                    error_message="timeout",
                ),
                RepoTask(
                    repo_full_name="a/4",
                    clone_url="x",
                    status=TaskStatus.SKIPPED,
                ),
            ],
        )

        report = generate_run_report(state)

        assert report.batch_id == "report-test"
        assert report.repos_scanned == 4
        assert report.repos_succeeded == 2
        assert report.repos_failed == 1
        assert report.repos_skipped == 1
        assert report.total_links_found == 15
        assert report.total_broken_links == 4
        assert report.total_fixes_generated == 3
        assert report.total_prs_submitted == 1
        assert len(report.errors) == 1
        assert report.errors[0]["repo"] == "a/3"

    def test_empty_batch(self) -> None:
        state = BatchState(
            batch_id="empty",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        report = generate_run_report(state)
        assert report.repos_scanned == 0
        assert report.duration_seconds >= 0


class TestGenerateCampaignMetrics:
    """T190: Campaign metrics aggregation (REQ-11)."""

    def test_acceptance_rate_and_avg_ttm(self, tmp_path) -> None:
        db_path = tmp_path / "campaign.db"
        collector = MetricsCollector(db_path)
        try:
            # Record 3 runs
            for i in range(3):
                report = RunReport(
                    batch_id=f"run-{i}",
                    started_at=datetime(2026, 1, i + 1, tzinfo=timezone.utc),
                    completed_at=datetime(2026, 1, i + 1, 1, tzinfo=timezone.utc),
                    repos_scanned=10,
                    repos_succeeded=10,
                    repos_failed=0,
                    repos_skipped=0,
                    total_links_found=50,
                    total_broken_links=10,
                    total_fixes_generated=8,
                    total_prs_submitted=3,
                    duration_seconds=3600.0,
                )
                collector.record_run(report)

            # Record 5 PR outcomes: 3 merged, 1 rejected, 1 open
            for i in range(3):
                collector.record_pr_outcome(PROutcome(
                    repo_full_name=f"o/merged{i}",
                    pr_url=f"https://github.com/o/merged{i}/pull/1",
                    submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    status="merged",
                    merged_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                    time_to_merge_hours=24.0,
                ))
            collector.record_pr_outcome(PROutcome(
                repo_full_name="o/rejected",
                pr_url="https://github.com/o/rejected/pull/1",
                submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                status="rejected",
                rejection_reason="not-wanted",
            ))
            collector.record_pr_outcome(PROutcome(
                repo_full_name="o/open",
                pr_url="https://github.com/o/open/pull/1",
                submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                status="open",
            ))
        finally:
            collector.close()

        metrics = generate_campaign_metrics(db_path)

        assert metrics.total_runs == 3
        assert metrics.total_repos_processed == 30
        assert metrics.total_prs_submitted == 9
        assert metrics.total_prs_merged == 3
        assert metrics.total_prs_rejected == 1
        assert metrics.total_prs_open == 1
        # acceptance_rate = 3 / (3 + 1) = 0.75
        assert abs(metrics.acceptance_rate - 0.75) < 0.01
        # avg_time_to_merge = 24.0 hours (all merged PRs have 24h)
        assert abs(metrics.avg_time_to_merge_hours - 24.0) < 0.01
        assert metrics.rejection_reasons == {"not-wanted": 1}

    def test_empty_database(self, tmp_path) -> None:
        db_path = tmp_path / "empty.db"
        metrics = generate_campaign_metrics(db_path)
        assert metrics.total_runs == 0
        assert metrics.acceptance_rate == 0.0
        assert metrics.avg_time_to_merge_hours == 0.0


class TestFormatReportText:
    """T200: Text report formatting (REQ-10)."""

    def test_all_fields_present(self) -> None:
        report = RunReport(
            batch_id="fmt-test",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            completed_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
            repos_scanned=100,
            repos_succeeded=90,
            repos_failed=8,
            repos_skipped=2,
            total_links_found=500,
            total_broken_links=50,
            total_fixes_generated=30,
            total_prs_submitted=20,
            duration_seconds=3600.0,
            errors=[{"repo": "a/b", "error_message": "fail"}],
        )

        text = format_report_text(report)

        assert "fmt-test" in text
        assert "100" in text
        assert "90" in text
        assert "8" in text
        assert "500" in text
        assert "50" in text
        assert "30" in text
        assert "20" in text
        assert "3600" in text
        assert "a/b" in text
        assert "fail" in text

    def test_no_errors_section(self) -> None:
        report = RunReport(
            batch_id="clean",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            completed_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
            repos_scanned=5,
            repos_succeeded=5,
            repos_failed=0,
            repos_skipped=0,
            total_links_found=10,
            total_broken_links=2,
            total_fixes_generated=1,
            total_prs_submitted=1,
            duration_seconds=100.0,
        )
        text = format_report_text(report)
        assert "Errors:" not in text


class TestFormatReportJson:
    """T210: JSON report formatting (REQ-10)."""

    def test_valid_json_with_all_fields(self) -> None:
        report = RunReport(
            batch_id="json-test",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            completed_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
            repos_scanned=10,
            repos_succeeded=8,
            repos_failed=2,
            repos_skipped=0,
            total_links_found=100,
            total_broken_links=20,
            total_fixes_generated=15,
            total_prs_submitted=5,
            duration_seconds=600.0,
        )

        json_str = format_report_json(report)
        data = json.loads(json_str)

        assert data["batch_id"] == "json-test"
        assert data["repos_scanned"] == 10
        assert data["repos_succeeded"] == 8
        assert data["total_prs_submitted"] == 5
        assert "started_at" in data
        assert "completed_at" in data


class TestFormatCampaignText:
    """Tests for campaign text formatting."""

    def test_all_fields(self) -> None:
        metrics = CampaignMetrics(
            total_runs=5,
            total_repos_processed=500,
            total_prs_submitted=50,
            total_prs_merged=30,
            total_prs_rejected=10,
            total_prs_open=10,
            acceptance_rate=0.75,
            avg_time_to_merge_hours=36.0,
            rejection_reasons={"not-wanted": 5, "duplicate": 3},
        )

        text = format_campaign_text(metrics)

        assert "5" in text  # total_runs
        assert "500" in text  # total_repos
        assert "75.0%" in text  # acceptance_rate
        assert "36.0h" in text  # avg_ttm
        assert "not-wanted" in text
