"""Event-driven metrics collector with SQLite persistence.

See LLD-019 §2.4 for MetricsCollector specification.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from gh_link_auditor.metrics.models import PROutcome, RunReport


class MetricsCollector:
    """Collects events during batch runs and persists metrics."""

    def __init__(self, db_path: Path) -> None:
        """Initialize with path to metrics SQLite database.

        Args:
            db_path: Path to SQLite file.
        """
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._create_tables()

    def _create_tables(self) -> None:
        """Create metrics tables if they don't exist."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS run_reports (
                batch_id TEXT PRIMARY KEY,
                started_at TEXT,
                completed_at TEXT,
                repos_scanned INTEGER,
                repos_succeeded INTEGER,
                repos_failed INTEGER,
                repos_skipped INTEGER,
                total_links_found INTEGER,
                total_broken_links INTEGER,
                total_fixes_generated INTEGER,
                total_prs_submitted INTEGER,
                duration_seconds REAL,
                errors_json TEXT
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS pr_outcomes (
                pr_url TEXT PRIMARY KEY,
                repo_full_name TEXT,
                submitted_at TEXT,
                status TEXT,
                merged_at TEXT,
                closed_at TEXT,
                rejection_reason TEXT,
                time_to_merge_hours REAL
            )
        """)
        self._conn.commit()

    def record_run(self, report: RunReport) -> None:
        """Persist a batch run report.

        Args:
            report: RunReport to store.
        """
        self._conn.execute(
            """
            INSERT OR REPLACE INTO run_reports
            (batch_id, started_at, completed_at, repos_scanned, repos_succeeded,
             repos_failed, repos_skipped, total_links_found, total_broken_links,
             total_fixes_generated, total_prs_submitted, duration_seconds, errors_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.batch_id,
                report.started_at.isoformat(),
                report.completed_at.isoformat(),
                report.repos_scanned,
                report.repos_succeeded,
                report.repos_failed,
                report.repos_skipped,
                report.total_links_found,
                report.total_broken_links,
                report.total_fixes_generated,
                report.total_prs_submitted,
                report.duration_seconds,
                json.dumps(report.errors),
            ),
        )
        self._conn.commit()

    def record_pr_outcome(self, outcome: PROutcome) -> None:
        """Record or update a PR outcome.

        Args:
            outcome: PROutcome to store.
        """
        self._conn.execute(
            """
            INSERT OR REPLACE INTO pr_outcomes
            (pr_url, repo_full_name, submitted_at, status, merged_at,
             closed_at, rejection_reason, time_to_merge_hours)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                outcome.pr_url,
                outcome.repo_full_name,
                outcome.submitted_at.isoformat(),
                outcome.status,
                outcome.merged_at.isoformat() if outcome.merged_at else None,
                outcome.closed_at.isoformat() if outcome.closed_at else None,
                outcome.rejection_reason,
                outcome.time_to_merge_hours,
            ),
        )
        self._conn.commit()

    def get_all_runs(self) -> list[RunReport]:
        """Load all run reports from the database.

        Returns:
            List of RunReport objects.
        """
        from datetime import datetime

        cursor = self._conn.execute("SELECT * FROM run_reports ORDER BY started_at")
        rows = cursor.fetchall()
        reports = []
        for row in rows:
            reports.append(
                RunReport(
                    batch_id=row[0],
                    started_at=datetime.fromisoformat(row[1]),
                    completed_at=datetime.fromisoformat(row[2]),
                    repos_scanned=row[3],
                    repos_succeeded=row[4],
                    repos_failed=row[5],
                    repos_skipped=row[6],
                    total_links_found=row[7],
                    total_broken_links=row[8],
                    total_fixes_generated=row[9],
                    total_prs_submitted=row[10],
                    duration_seconds=row[11],
                    errors=json.loads(row[12]) if row[12] else [],
                )
            )
        return reports

    def get_all_pr_outcomes(self) -> list[PROutcome]:
        """Load all PR outcomes from the database.

        Returns:
            List of PROutcome objects.
        """
        from datetime import datetime

        cursor = self._conn.execute("SELECT * FROM pr_outcomes")
        rows = cursor.fetchall()
        outcomes = []
        for row in rows:
            outcomes.append(
                PROutcome(
                    pr_url=row[0],
                    repo_full_name=row[1],
                    submitted_at=datetime.fromisoformat(row[2]),
                    status=row[3],
                    merged_at=(
                        datetime.fromisoformat(row[4]) if row[4] else None
                    ),
                    closed_at=(
                        datetime.fromisoformat(row[5]) if row[5] else None
                    ),
                    rejection_reason=row[6],
                    time_to_merge_hours=row[7],
                )
            )
        return outcomes

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
