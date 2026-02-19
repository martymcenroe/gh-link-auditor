"""Tests for metrics collection.

Covers LLD-019 scenarios:
- T190 (partial): Campaign metrics aggregation via collector (REQ-11)
"""

from __future__ import annotations

from datetime import datetime, timezone

from gh_link_auditor.metrics.collector import MetricsCollector
from gh_link_auditor.metrics.models import PROutcome, RunReport


class TestMetricsCollector:
    """Tests for MetricsCollector persistence."""

    def test_record_and_retrieve_run(self, tmp_path) -> None:
        db_path = tmp_path / "metrics.db"
        collector = MetricsCollector(db_path)
        try:
            report = RunReport(
                batch_id="test-001",
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
                duration_seconds=3600.0,
                errors=[{"repo": "a/b", "error_message": "boom"}],
            )
            collector.record_run(report)

            runs = collector.get_all_runs()
            assert len(runs) == 1
            assert runs[0].batch_id == "test-001"
            assert runs[0].repos_scanned == 10
            assert runs[0].errors == [{"repo": "a/b", "error_message": "boom"}]
        finally:
            collector.close()

    def test_record_and_retrieve_pr_outcome(self, tmp_path) -> None:
        db_path = tmp_path / "metrics.db"
        collector = MetricsCollector(db_path)
        try:
            outcome = PROutcome(
                repo_full_name="owner/repo",
                pr_url="https://github.com/owner/repo/pull/1",
                submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                status="merged",
                merged_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                time_to_merge_hours=24.0,
            )
            collector.record_pr_outcome(outcome)

            outcomes = collector.get_all_pr_outcomes()
            assert len(outcomes) == 1
            assert outcomes[0].status == "merged"
            assert outcomes[0].time_to_merge_hours == 24.0
        finally:
            collector.close()

    def test_upsert_run(self, tmp_path) -> None:
        db_path = tmp_path / "metrics.db"
        collector = MetricsCollector(db_path)
        try:
            report = RunReport(
                batch_id="upsert-test",
                started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                completed_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
                repos_scanned=5,
                repos_succeeded=5,
                repos_failed=0,
                repos_skipped=0,
                total_links_found=50,
                total_broken_links=10,
                total_fixes_generated=8,
                total_prs_submitted=3,
                duration_seconds=1800.0,
            )
            collector.record_run(report)

            # Update same batch_id
            report.repos_scanned = 10
            collector.record_run(report)

            runs = collector.get_all_runs()
            assert len(runs) == 1
            assert runs[0].repos_scanned == 10
        finally:
            collector.close()

    def test_multiple_runs(self, tmp_path) -> None:
        db_path = tmp_path / "metrics.db"
        collector = MetricsCollector(db_path)
        try:
            for i in range(3):
                report = RunReport(
                    batch_id=f"run-{i}",
                    started_at=datetime(2026, 1, i + 1, tzinfo=timezone.utc),
                    completed_at=datetime(2026, 1, i + 1, 1, tzinfo=timezone.utc),
                    repos_scanned=10 * (i + 1),
                    repos_succeeded=10 * (i + 1),
                    repos_failed=0,
                    repos_skipped=0,
                    total_links_found=0,
                    total_broken_links=0,
                    total_fixes_generated=0,
                    total_prs_submitted=i + 1,
                    duration_seconds=100.0,
                )
                collector.record_run(report)

            runs = collector.get_all_runs()
            assert len(runs) == 3
        finally:
            collector.close()
