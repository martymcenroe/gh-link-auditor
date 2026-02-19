"""Real-time batch progress tracking with state serialization.

See LLD-019 §2.4 for BatchProgressTracker specification.
"""

from __future__ import annotations

import time

from gh_link_auditor.batch.models import RepoTask, TaskStatus


class BatchProgressTracker:
    """Tracks and displays real-time batch progress."""

    def __init__(self, total: int) -> None:
        """Initialize with total number of repos to process.

        Args:
            total: Total number of repos.
        """
        self.total = total
        self.completed = 0
        self.failed = 0
        self.fixes = 0
        self.prs = 0
        self.errors = 0
        self._start_time = time.monotonic()

    def update(self, task: RepoTask) -> None:
        """Record completion of a task and refresh counters.

        Args:
            task: Completed RepoTask.
        """
        if task.status == TaskStatus.COMPLETED:
            self.completed += 1
            self.fixes += task.fixes_generated
            if task.pr_submitted:
                self.prs += 1
        elif task.status == TaskStatus.FAILED:
            self.failed += 1
            self.errors += 1
        elif task.status == TaskStatus.SKIPPED:
            self.completed += 1

    def display(self) -> str:
        """Return a formatted progress string.

        Returns:
            Progress string like '347/2000 | 12 fixes | 3 PRs | 2 errors | ETA 1h23m'.
        """
        processed = self.completed + self.failed
        eta = self._estimate_eta(processed)
        return (
            f"{processed}/{self.total} | "
            f"{self.fixes} fixes | "
            f"{self.prs} PRs | "
            f"{self.errors} errors | "
            f"ETA {eta}"
        )

    def _estimate_eta(self, processed: int) -> str:
        """Estimate time remaining.

        Args:
            processed: Number of repos processed so far.

        Returns:
            Human-readable ETA string.
        """
        if processed == 0:
            return "calculating..."

        elapsed = time.monotonic() - self._start_time
        rate = processed / elapsed
        remaining = self.total - processed
        eta_seconds = remaining / rate

        if eta_seconds < 60:
            return f"{eta_seconds:.0f}s"
        if eta_seconds < 3600:
            return f"{eta_seconds / 60:.0f}m"
        hours = int(eta_seconds // 3600)
        minutes = int((eta_seconds % 3600) // 60)
        return f"{hours}h{minutes:02d}m"

    def summary(self) -> dict[str, int]:
        """Return summary counters.

        Returns:
            Dict with completed, failed, fixes, prs, errors.
        """
        return {
            "completed": self.completed,
            "failed": self.failed,
            "fixes": self.fixes,
            "prs": self.prs,
            "errors": self.errors,
        }
