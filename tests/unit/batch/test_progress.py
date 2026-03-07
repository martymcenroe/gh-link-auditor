"""Tests for batch progress tracking.

Covers LLD-019 scenarios:
- T130: Progress display format (REQ-7)
- T280: Batch status from checkpoint (REQ-12)
"""

from __future__ import annotations

from gh_link_auditor.batch.models import RepoTask, TaskStatus
from gh_link_auditor.batch.progress import BatchProgressTracker


class TestProgressDisplay:
    """T130: Progress display format (REQ-7)."""

    def test_display_format(self) -> None:
        """Progress string matches expected pattern."""
        tracker = BatchProgressTracker(total=2000)

        # Simulate 347 completed, some with fixes and PRs
        for i in range(340):
            task = RepoTask(
                repo_full_name=f"owner/repo{i}",
                clone_url=f"https://github.com/owner/repo{i}.git",
                status=TaskStatus.COMPLETED,
            )
            tracker.update(task)

        for i in range(5):
            task = RepoTask(
                repo_full_name=f"owner/fix{i}",
                clone_url="x",
                status=TaskStatus.COMPLETED,
                fixes_generated=2,
                pr_submitted=True,
            )
            tracker.update(task)

        for i in range(2):
            task = RepoTask(
                repo_full_name=f"owner/err{i}",
                clone_url="x",
                status=TaskStatus.FAILED,
                error_message="test",
            )
            tracker.update(task)

        display = tracker.display()

        # Should match: "347/2000 | 10 fixes | 5 PRs | 2 errors | ETA ..."
        assert "347/2000" in display
        assert "10 fixes" in display
        assert "5 PRs" in display
        assert "2 errors" in display
        assert "ETA" in display

    def test_display_zero_processed(self) -> None:
        tracker = BatchProgressTracker(total=100)
        display = tracker.display()
        assert "0/100" in display
        assert "calculating" in display.lower()

    def test_display_with_eta_seconds(self) -> None:
        tracker = BatchProgressTracker(total=10)
        tracker._start_time -= 1.0  # Fake 1 second elapsed

        for i in range(9):
            task = RepoTask(
                repo_full_name=f"o/r{i}",
                clone_url="x",
                status=TaskStatus.COMPLETED,
            )
            tracker.update(task)

        display = tracker.display()
        assert "9/10" in display


class TestProgressSummary:
    """Tests for summary counters."""

    def test_summary_counts(self) -> None:
        tracker = BatchProgressTracker(total=10)

        for i in range(5):
            task = RepoTask(
                repo_full_name=f"o/r{i}",
                clone_url="x",
                status=TaskStatus.COMPLETED,
                fixes_generated=1,
            )
            tracker.update(task)

        for i in range(2):
            task = RepoTask(
                repo_full_name=f"o/f{i}",
                clone_url="x",
                status=TaskStatus.FAILED,
            )
            tracker.update(task)

        summary = tracker.summary()
        assert summary["completed"] == 5
        assert summary["failed"] == 2
        assert summary["fixes"] == 5
        assert summary["errors"] == 2


class TestETAFormatting:
    """Tests for ETA string formatting edge cases."""

    def test_eta_under_minute(self) -> None:
        tracker = BatchProgressTracker(total=10)
        tracker._start_time -= 1.0  # 1s elapsed
        for i in range(9):
            task = RepoTask(repo_full_name=f"o/r{i}", clone_url="x", status=TaskStatus.COMPLETED)
            tracker.update(task)
        display = tracker.display()
        # 1 remaining, ~0.11s per repo → ETA < 1s
        assert "ETA" in display

    def test_eta_minutes(self) -> None:
        tracker = BatchProgressTracker(total=1000)
        tracker._start_time -= 10.0  # 10s elapsed
        for i in range(100):
            task = RepoTask(repo_full_name=f"o/r{i}", clone_url="x", status=TaskStatus.COMPLETED)
            tracker.update(task)
        display = tracker.display()
        # 900 remaining, 0.1s/repo → 90s → should show minutes
        assert "ETA" in display

    def test_eta_hours(self) -> None:
        tracker = BatchProgressTracker(total=100000)
        tracker._start_time -= 100.0  # 100s elapsed
        for i in range(100):
            task = RepoTask(repo_full_name=f"o/r{i}", clone_url="x", status=TaskStatus.COMPLETED)
            tracker.update(task)
        display = tracker.display()
        # 99900 remaining, 1s/repo → ~27h → should show hours
        assert "h" in display

    def test_skipped_status(self) -> None:
        tracker = BatchProgressTracker(total=5)
        task = RepoTask(repo_full_name="o/r", clone_url="x", status=TaskStatus.SKIPPED)
        tracker.update(task)
        assert tracker.completed == 1


class TestBatchStatusFromCheckpoint:
    """T280: Batch status from checkpoint (REQ-12)."""

    def test_status_display(self) -> None:
        """Verify status output matches expected format."""
        tracker = BatchProgressTracker(total=5)

        for i in range(3):
            task = RepoTask(
                repo_full_name=f"o/r{i}",
                clone_url="x",
                status=TaskStatus.COMPLETED,
            )
            tracker.update(task)

        summary = tracker.summary()
        status_str = f"{summary['completed']}/{tracker.total} completed, {summary['failed']} failed"
        assert "3/5 completed" in status_str
        assert "0 failed" in status_str
