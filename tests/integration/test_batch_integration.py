"""Integration test: engine + rate limiter + progress across multiple mock repos.

Covers LLD-019 scenario:
- T290: Integration: full mock batch (REQ-1)
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from gh_link_auditor.batch.engine import run_batch
from gh_link_auditor.batch.models import BatchConfig, TaskStatus
from gh_link_auditor.metrics.collector import MetricsCollector


class TestFullMockBatch:
    """T290: Integration test with 3 repos, mocked pipeline + API."""

    def test_end_to_end_batch(self, tmp_path) -> None:
        """Full pipeline: load targets, process, checkpoint, report, metrics."""
        # Setup target list
        targets = [
            {"full_name": f"org/repo-{i}"}
            for i in range(3)
        ]
        target_file = tmp_path / "targets.json"
        target_file.write_text(json.dumps(targets))

        # Setup metrics DB
        db_path = tmp_path / "metrics.db"

        # Mock process to simulate realistic results
        async def mock_process(task, tm, rl, config):
            from gh_link_auditor.batch.models import now_utc

            task.started_at = now_utc()
            task.links_found = 10
            task.broken_links = 2
            task.fixes_generated = 1
            task.pr_submitted = not config.dry_run
            if task.pr_submitted:
                task.pr_url = f"https://github.com/{task.repo_full_name}/pull/1"
            task.status = TaskStatus.COMPLETED
            task.completed_at = now_utc()
            return task

        config = BatchConfig(
            target_list_path=target_file,
            concurrency=2,
            clone_dir=tmp_path / "clones",
            checkpoint_interval=2,
        )

        with patch("gh_link_auditor.batch.engine._process_single_repo", side_effect=mock_process):
            report = asyncio.run(run_batch(config))

        # Verify report
        assert report.repos_scanned == 3
        assert report.repos_succeeded == 3
        assert report.repos_failed == 0
        assert report.total_links_found == 30
        assert report.total_broken_links == 6
        assert report.total_fixes_generated == 3
        assert report.total_prs_submitted == 3
        assert report.duration_seconds > 0

        # Verify metrics can be stored
        collector = MetricsCollector(db_path)
        try:
            collector.record_run(report)
            runs = collector.get_all_runs()
            assert len(runs) == 1
            assert runs[0].batch_id == report.batch_id
        finally:
            collector.close()

    def test_dry_run_integration(self, tmp_path) -> None:
        """Dry run: full pipeline without PR submission."""
        targets = [{"full_name": "org/repo-0"}]
        target_file = tmp_path / "targets.json"
        target_file.write_text(json.dumps(targets))

        config = BatchConfig(
            target_list_path=target_file,
            concurrency=1,
            dry_run=True,
            clone_dir=tmp_path / "clones",
        )

        report = asyncio.run(run_batch(config))

        assert report.repos_scanned == 1
        assert report.repos_succeeded == 1
        assert report.total_prs_submitted == 0

    def test_mixed_success_failure_integration(self, tmp_path) -> None:
        """Some repos succeed, some fail — error isolation verified."""
        targets = [
            {"full_name": f"org/repo-{i}"}
            for i in range(4)
        ]
        target_file = tmp_path / "targets.json"
        target_file.write_text(json.dumps(targets))

        async def mock_process(task, tm, rl, config):
            from gh_link_auditor.batch.models import now_utc

            task.started_at = now_utc()
            # Fail every other repo
            if int(task.repo_full_name.split("-")[-1]) % 2 == 1:
                task.status = TaskStatus.FAILED
                task.error_message = "simulated failure"
            else:
                task.status = TaskStatus.COMPLETED
                task.links_found = 5
            task.completed_at = now_utc()
            return task

        config = BatchConfig(
            target_list_path=target_file,
            concurrency=1,
            clone_dir=tmp_path / "clones",
        )

        with patch("gh_link_auditor.batch.engine._process_single_repo", side_effect=mock_process):
            report = asyncio.run(run_batch(config))

        assert report.repos_scanned == 4
        assert report.repos_succeeded == 2
        assert report.repos_failed == 2
        assert len(report.errors) == 2
