"""Thin wrapper around UnifiedDatabase for backward compatibility.

Preserves the MetricsCollector API so existing consumers (reporter,
pr_tracker, CLI) continue to work unchanged.
"""

from __future__ import annotations

from pathlib import Path

from gh_link_auditor.metrics.models import PROutcome, RunReport
from gh_link_auditor.unified_db import UnifiedDatabase


class MetricsCollector:
    """Backward-compatible facade delegating to UnifiedDatabase."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._db = UnifiedDatabase(db_path)

    def record_run(self, report: RunReport) -> None:
        self._db.record_run(report)

    def record_pr_outcome(self, outcome: PROutcome) -> None:
        self._db.record_pr_outcome(outcome)

    def get_all_runs(self) -> list[RunReport]:
        return self._db.get_all_runs()

    def get_all_pr_outcomes(self) -> list[PROutcome]:
        return self._db.get_all_pr_outcomes()

    def close(self) -> None:
        self._db.close()
