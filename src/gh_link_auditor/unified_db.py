"""Unified SQLite database for gh-link-auditor.

Consolidates state_db, metrics collector, and TinyDB state store into
a single database file. Schema version 2 with migration from v1.

See plan: Unified Database + 15 Issue Implementation Run.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gh_link_auditor.metrics.models import PROutcome, RunReport
from gh_link_auditor.models import BlacklistEntry, InteractionRecord, InteractionStatus

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".ghla" / "ghla.db"
SCHEMA_VERSION = 2


class UnifiedDatabase:
    """Single SQLite database backing all gh-link-auditor persistence."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._bootstrap()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> UnifiedDatabase:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Schema bootstrap + migration
    # ------------------------------------------------------------------

    def _bootstrap(self) -> None:
        with self._conn:
            self._conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = self._conn.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                self._create_all_tables()
                self._conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            elif row["version"] < SCHEMA_VERSION:
                self._migrate(row["version"])
            # else: already at current version

    def _create_all_tables(self) -> None:
        c = self._conn

        # --- repos: central repo registry ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS repos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL UNIQUE,
                stars INTEGER,
                contributors INTEGER,
                pushed_at TEXT,
                has_contributing INTEGER DEFAULT 0,
                contributing_warnings TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_repos_full_name ON repos (full_name)")

        # --- scans: every pipeline run against a repo ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id INTEGER REFERENCES repos(id),
                run_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                dead_links_found INTEGER DEFAULT 0,
                fixes_generated INTEGER DEFAULT 0,
                pr_submitted INTEGER DEFAULT 0,
                decision TEXT,
                duration_seconds REAL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_scans_repo_id ON scans (repo_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_scans_run_id ON scans (run_id)")

        # --- findings: every dead link found ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER REFERENCES scans(id),
                url TEXT NOT NULL,
                source_file TEXT NOT NULL,
                line_number INTEGER,
                http_status INTEGER,
                error_type TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                replacement_url TEXT,
                confidence REAL,
                is_historical_file INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_findings_scan_id ON findings (scan_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_findings_url ON findings (url)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_findings_status ON findings (status)")

        # --- interactions: legacy bot interactions (preserved from state_db) ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_url TEXT NOT NULL,
                broken_url TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                pr_url TEXT,
                maintainer TEXT,
                notes TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_interactions_repo_url ON interactions (repo_url, broken_url)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_interactions_maintainer ON interactions (maintainer)")

        # --- blacklist: repo/maintainer blacklist ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_url TEXT,
                maintainer TEXT,
                reason TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL,
                expires_at TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_blacklist_repo ON blacklist (repo_url)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_blacklist_maintainer ON blacklist (maintainer)")

        # --- run_reports: batch run summaries ---
        c.execute("""
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

        # --- pr_outcomes: PR status tracking ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS pr_outcomes (
                pr_url TEXT PRIMARY KEY,
                repo_full_name TEXT,
                repo_id INTEGER REFERENCES repos(id),
                submitted_at TEXT,
                status TEXT,
                merged_at TEXT,
                closed_at TEXT,
                rejection_reason TEXT,
                time_to_merge_hours REAL,
                is_tier2 INTEGER DEFAULT 0
            )
        """)

        # --- repo_trust: per-repo trust level (#125 placeholder) ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS repo_trust (
                repo_id INTEGER PRIMARY KEY REFERENCES repos(id),
                trust_level TEXT NOT NULL DEFAULT 'new',
                first_pr_at TEXT,
                first_merge_at TEXT,
                total_prs INTEGER DEFAULT 0,
                total_merges INTEGER DEFAULT 0,
                is_blacklisted INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL
            )
        """)

        # --- recheck_queue: snoozed findings (#125 placeholder) ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS recheck_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                finding_id INTEGER REFERENCES findings(id),
                snooze_until TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_recheck_snooze ON recheck_queue (snooze_until)")

        # --- submissions: DocFix Bot PR tracking (replaces TinyDB) ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_owner TEXT NOT NULL,
                repo_name TEXT NOT NULL,
                branch_name TEXT,
                pr_number INTEGER,
                pr_url TEXT,
                status TEXT,
                broken_links_json TEXT,
                submitted_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_submissions_repo ON submissions (repo_owner, repo_name)")

        # --- api_calls: rate limiting timestamps (replaces TinyDB) ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS api_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL
            )
        """)

        # --- url_check_cache: URL check results (#122) ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS url_check_cache (
                url TEXT PRIMARY KEY,
                http_status INTEGER,
                final_url TEXT,
                is_bot_blocked INTEGER DEFAULT 0,
                retry_count INTEGER DEFAULT 0,
                last_checked_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)

        # --- archive_cache: CDX/Wayback results (#123) ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS archive_cache (
                url TEXT PRIMARY KEY,
                has_snapshot INTEGER DEFAULT 0,
                snapshot_url TEXT,
                snapshot_timestamp TEXT,
                title TEXT,
                retry_count INTEGER DEFAULT 0,
                last_checked_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)

        # --- pipeline_runs: replaces JSON state files ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_id TEXT PRIMARY KEY,
                target TEXT NOT NULL,
                last_node TEXT,
                state_json TEXT,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running'
            )
        """)

    # ------------------------------------------------------------------
    # Migration v1 -> v2
    # ------------------------------------------------------------------

    def _migrate(self, from_version: int) -> None:
        if from_version == 1:
            self._migrate_v1_to_v2()

    def _migrate_v1_to_v2(self) -> None:
        logger.info("Migrating schema v1 → v2")
        # v1 had interactions + blacklist only. We add new tables and
        # a 'source' column to blacklist.
        c = self._conn

        # Add source column to blacklist if missing
        cols = {row[1] for row in c.execute("PRAGMA table_info(blacklist)").fetchall()}
        if "source" not in cols:
            c.execute("ALTER TABLE blacklist ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")

        # Create all new tables (IF NOT EXISTS is safe)
        self._create_all_tables()

        # Bump version
        c.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
        logger.info("Migration to v2 complete")

    # ------------------------------------------------------------------
    # External migration: import from metrics.db
    # ------------------------------------------------------------------

    def import_from_metrics_db(self, metrics_db_path: str | Path) -> int:
        """Import run_reports and pr_outcomes from a separate metrics.db.

        Returns number of records imported.
        """
        p = Path(metrics_db_path)
        if not p.exists():
            return 0

        src = sqlite3.connect(str(p))
        src.row_factory = sqlite3.Row
        imported = 0

        try:
            # Import run_reports
            for row in src.execute("SELECT * FROM run_reports").fetchall():
                self._conn.execute(
                    """INSERT OR IGNORE INTO run_reports
                    (batch_id, started_at, completed_at, repos_scanned,
                     repos_succeeded, repos_failed, repos_skipped,
                     total_links_found, total_broken_links,
                     total_fixes_generated, total_prs_submitted,
                     duration_seconds, errors_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    tuple(row),
                )
                imported += 1

            # Import pr_outcomes
            for row in src.execute("SELECT * FROM pr_outcomes").fetchall():
                self._conn.execute(
                    """INSERT OR IGNORE INTO pr_outcomes
                    (pr_url, repo_full_name, submitted_at, status,
                     merged_at, closed_at, rejection_reason, time_to_merge_hours)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    tuple(row),
                )
                imported += 1

            self._conn.commit()
        finally:
            src.close()

        logger.info("Imported %d records from metrics.db", imported)
        return imported

    # ------------------------------------------------------------------
    # External migration: import from TinyDB
    # ------------------------------------------------------------------

    def import_from_tinydb(self, tinydb_path: str | Path) -> int:
        """Import submissions and api_calls from TinyDB JSON file.

        Returns number of records imported.
        """
        p = Path(tinydb_path)
        if not p.exists():
            return 0

        data = json.loads(p.read_text())
        imported = 0
        now = _now_iso()

        # Import submissions
        submissions = data.get("submissions", {})
        for _key, record in submissions.items():
            repo = record.get("repository", {})
            links_json = json.dumps(record.get("broken_links_fixed", []))
            self._conn.execute(
                """INSERT INTO submissions
                (repo_owner, repo_name, branch_name, pr_number, pr_url,
                 status, broken_links_json, submitted_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (
                    repo.get("owner", ""),
                    repo.get("repo", ""),
                    record.get("branch_name"),
                    record.get("pr_number"),
                    record.get("pr_url"),
                    record.get("status"),
                    links_json,
                    record.get("submitted_at", now),
                ),
            )
            imported += 1

        # Import api_calls
        api_calls = data.get("api_calls", {})
        for _key, record in api_calls.items():
            self._conn.execute(
                "INSERT INTO api_calls (timestamp) VALUES (?)",
                (record.get("timestamp", now),),
            )
            imported += 1

        self._conn.commit()
        logger.info("Imported %d records from TinyDB", imported)
        return imported

    # ------------------------------------------------------------------
    # Interactions (backward-compatible with StateDatabase)
    # ------------------------------------------------------------------

    def record_interaction(
        self,
        repo_url: str,
        broken_url: str,
        status: InteractionStatus,
        pr_url: str | None = None,
        maintainer: str | None = None,
        notes: str | None = None,
    ) -> int:
        now = _now_iso()
        with self._conn:
            cursor = self._conn.execute(
                """INSERT INTO interactions
                (repo_url, broken_url, status, created_at, updated_at, pr_url, maintainer, notes)
                VALUES (?,?,?,?,?,?,?,?)""",
                (repo_url, broken_url, status.value, now, now, pr_url, maintainer, notes),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def update_interaction_status(
        self,
        record_id: int,
        new_status: InteractionStatus,
        pr_url: str | None = None,
        notes: str | None = None,
    ) -> bool:
        now = _now_iso()
        parts = ["status = ?", "updated_at = ?"]
        params: list[Any] = [new_status.value, now]
        if pr_url is not None:
            parts.append("pr_url = ?")
            params.append(pr_url)
        if notes is not None:
            parts.append("notes = ?")
            params.append(notes)
        params.append(record_id)
        with self._conn:
            cursor = self._conn.execute(
                f"UPDATE interactions SET {', '.join(parts)} WHERE id = ?",  # noqa: S608
                params,
            )
            return cursor.rowcount > 0

    def get_interaction(self, repo_url: str, broken_url: str) -> InteractionRecord | None:
        row = self._conn.execute(
            """SELECT id, repo_url, broken_url, status, created_at, updated_at,
                      pr_url, maintainer, notes
               FROM interactions
               WHERE repo_url = ? AND broken_url = ?
               ORDER BY created_at DESC LIMIT 1""",
            (repo_url, broken_url),
        ).fetchone()
        if row is None:
            return None
        return _row_to_interaction(row)

    def has_been_submitted(self, repo_url: str, broken_url: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM interactions WHERE repo_url = ? AND broken_url = ? LIMIT 1",
            (repo_url, broken_url),
        ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Blacklist (backward-compatible with StateDatabase)
    # ------------------------------------------------------------------

    def add_to_blacklist(
        self,
        repo_url: str | None = None,
        maintainer: str | None = None,
        reason: str = "",
        expires_at: datetime | None = None,
        source: str = "manual",
    ) -> int:
        if repo_url is None and maintainer is None:
            raise ValueError("At least one of repo_url or maintainer must be provided")
        now = _now_iso()
        expires_str = expires_at.isoformat() if expires_at is not None else None
        with self._conn:
            cursor = self._conn.execute(
                """INSERT INTO blacklist
                (repo_url, maintainer, reason, source, created_at, expires_at)
                VALUES (?,?,?,?,?,?)""",
                (repo_url, maintainer, reason, source, now, expires_str),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def remove_from_blacklist(self, entry_id: int) -> bool:
        with self._conn:
            cursor = self._conn.execute("DELETE FROM blacklist WHERE id = ?", (entry_id,))
            return cursor.rowcount > 0

    def is_blacklisted(self, repo_url: str, maintainer: str | None = None) -> bool:
        now = _now_iso()
        row = self._conn.execute(
            """SELECT 1 FROM blacklist
               WHERE repo_url = ? AND (expires_at IS NULL OR expires_at > ?)
               LIMIT 1""",
            (repo_url, now),
        ).fetchone()
        if row is not None:
            return True
        if maintainer is not None:
            row = self._conn.execute(
                """SELECT 1 FROM blacklist
                   WHERE maintainer = ? AND (expires_at IS NULL OR expires_at > ?)
                   LIMIT 1""",
                (maintainer, now),
            ).fetchone()
            if row is not None:
                return True
        return False

    def get_blacklist(self) -> list[BlacklistEntry]:
        now = _now_iso()
        rows = self._conn.execute(
            """SELECT id, repo_url, maintainer, reason, created_at, expires_at
               FROM blacklist
               WHERE expires_at IS NULL OR expires_at > ?
               ORDER BY created_at DESC""",
            (now,),
        ).fetchall()
        return [_row_to_blacklist(r) for r in rows]

    def can_submit_fix(self, repo_url: str, broken_url: str, maintainer: str | None = None) -> tuple[bool, str]:
        if self.is_blacklisted(repo_url, maintainer):
            return (False, "blacklisted")
        if self.has_been_submitted(repo_url, broken_url):
            return (False, "already submitted")
        return (True, "ok")

    def get_stats(self) -> dict[str, Any]:
        stats: dict[str, Any] = {}
        row = self._conn.execute("SELECT COUNT(*) AS cnt FROM interactions").fetchone()
        stats["total_interactions"] = row["cnt"]
        rows = self._conn.execute("SELECT status, COUNT(*) AS cnt FROM interactions GROUP BY status").fetchall()
        stats["by_status"] = {r["status"]: r["cnt"] for r in rows}
        now = _now_iso()
        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM blacklist WHERE expires_at IS NULL OR expires_at > ?",
            (now,),
        ).fetchone()
        stats["active_blacklist_entries"] = row["cnt"]
        row = self._conn.execute("SELECT COUNT(*) AS cnt FROM blacklist").fetchone()
        stats["total_blacklist_entries"] = row["cnt"]
        return stats

    # ------------------------------------------------------------------
    # Run Reports (backward-compatible with MetricsCollector)
    # ------------------------------------------------------------------

    def record_run(self, report: RunReport) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO run_reports
            (batch_id, started_at, completed_at, repos_scanned, repos_succeeded,
             repos_failed, repos_skipped, total_links_found, total_broken_links,
             total_fixes_generated, total_prs_submitted, duration_seconds, errors_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
        self._conn.execute(
            """INSERT OR REPLACE INTO pr_outcomes
            (pr_url, repo_full_name, submitted_at, status,
             merged_at, closed_at, rejection_reason, time_to_merge_hours)
            VALUES (?,?,?,?,?,?,?,?)""",
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
        cursor = self._conn.execute("SELECT * FROM run_reports ORDER BY started_at")
        rows = cursor.fetchall()
        reports = []
        for row in rows:
            reports.append(
                RunReport(
                    batch_id=row["batch_id"],
                    started_at=datetime.fromisoformat(row["started_at"]),
                    completed_at=datetime.fromisoformat(row["completed_at"]),
                    repos_scanned=row["repos_scanned"],
                    repos_succeeded=row["repos_succeeded"],
                    repos_failed=row["repos_failed"],
                    repos_skipped=row["repos_skipped"],
                    total_links_found=row["total_links_found"],
                    total_broken_links=row["total_broken_links"],
                    total_fixes_generated=row["total_fixes_generated"],
                    total_prs_submitted=row["total_prs_submitted"],
                    duration_seconds=row["duration_seconds"],
                    errors=json.loads(row["errors_json"]) if row["errors_json"] else [],
                )
            )
        return reports

    def get_all_pr_outcomes(self) -> list[PROutcome]:
        cursor = self._conn.execute("SELECT * FROM pr_outcomes")
        rows = cursor.fetchall()
        outcomes = []
        for row in rows:
            outcomes.append(
                PROutcome(
                    pr_url=row["pr_url"],
                    repo_full_name=row["repo_full_name"],
                    submitted_at=datetime.fromisoformat(row["submitted_at"]),
                    status=row["status"],
                    merged_at=datetime.fromisoformat(row["merged_at"]) if row["merged_at"] else None,
                    closed_at=datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else None,
                    rejection_reason=row["rejection_reason"],
                    time_to_merge_hours=row["time_to_merge_hours"],
                )
            )
        return outcomes

    # ------------------------------------------------------------------
    # Submissions (backward-compatible with TinyDB StateStore)
    # ------------------------------------------------------------------

    def record_submission(
        self,
        repo_owner: str,
        repo_name: str,
        branch_name: str | None,
        pr_number: int | None,
        pr_url: str | None,
        status: str | None,
        broken_links: list[dict[str, Any]],
        submitted_at: str | None = None,
    ) -> int:
        now = submitted_at or _now_iso()
        links_json = json.dumps(broken_links)
        with self._conn:
            cursor = self._conn.execute(
                """INSERT INTO submissions
                (repo_owner, repo_name, branch_name, pr_number, pr_url,
                 status, broken_links_json, submitted_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (repo_owner, repo_name, branch_name, pr_number, pr_url, status, links_json, now),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def was_link_already_fixed(self, repo_owner: str, repo_name: str, url: str) -> bool:
        rows = self._conn.execute(
            "SELECT broken_links_json FROM submissions WHERE repo_owner = ? AND repo_name = ?",
            (repo_owner, repo_name),
        ).fetchall()
        for row in rows:
            links = json.loads(row["broken_links_json"]) if row["broken_links_json"] else []
            for link in links:
                if link.get("original_url") == url:
                    return True
        return False

    def get_daily_submission_count(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM submissions WHERE submitted_at LIKE ?",
            (f"{today}%",),
        ).fetchone()
        return row["cnt"]

    # ------------------------------------------------------------------
    # API Calls (backward-compatible with TinyDB StateStore)
    # ------------------------------------------------------------------

    def increment_api_count(self) -> None:
        now = _now_iso()
        self._conn.execute("INSERT INTO api_calls (timestamp) VALUES (?)", (now,))
        self._conn.commit()

    def get_hourly_api_count(self) -> int:
        hour_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM api_calls WHERE timestamp LIKE ?",
            (f"{hour_prefix}%",),
        ).fetchone()
        return row["cnt"]

    # ------------------------------------------------------------------
    # URL Check Cache (#122)
    # ------------------------------------------------------------------

    def cache_url_check(
        self,
        url: str,
        http_status: int | None,
        final_url: str | None = None,
        is_bot_blocked: bool = False,
        retry_count: int = 0,
        ttl_hours: int = 24,
    ) -> None:
        now = datetime.now(timezone.utc)
        expires = now.replace(hour=now.hour + ttl_hours) if ttl_hours < 24 else now.replace(day=now.day + 1)
        # Simpler: just add hours
        from datetime import timedelta

        expires = now + timedelta(hours=ttl_hours)
        self._conn.execute(
            """INSERT OR REPLACE INTO url_check_cache
            (url, http_status, final_url, is_bot_blocked, retry_count,
             last_checked_at, expires_at)
            VALUES (?,?,?,?,?,?,?)""",
            (url, http_status, final_url, int(is_bot_blocked), retry_count, now.isoformat(), expires.isoformat()),
        )
        self._conn.commit()

    def get_cached_url_check(self, url: str) -> dict[str, Any] | None:
        now = _now_iso()
        row = self._conn.execute(
            "SELECT * FROM url_check_cache WHERE url = ? AND expires_at > ?",
            (url, now),
        ).fetchone()
        if row is None:
            return None
        return {
            "url": row["url"],
            "http_status": row["http_status"],
            "final_url": row["final_url"],
            "is_bot_blocked": bool(row["is_bot_blocked"]),
            "retry_count": row["retry_count"],
            "last_checked_at": row["last_checked_at"],
        }

    # ------------------------------------------------------------------
    # Archive Cache (#123)
    # ------------------------------------------------------------------

    def cache_archive_result(
        self,
        url: str,
        has_snapshot: bool,
        snapshot_url: str | None = None,
        snapshot_timestamp: str | None = None,
        title: str | None = None,
        retry_count: int = 0,
        ttl_hours: int = 168,
    ) -> None:
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=ttl_hours)
        self._conn.execute(
            """INSERT OR REPLACE INTO archive_cache
            (url, has_snapshot, snapshot_url, snapshot_timestamp, title,
             retry_count, last_checked_at, expires_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                url,
                int(has_snapshot),
                snapshot_url,
                snapshot_timestamp,
                title,
                retry_count,
                now.isoformat(),
                expires.isoformat(),
            ),
        )
        self._conn.commit()

    def get_cached_archive(self, url: str) -> dict[str, Any] | None:
        now = _now_iso()
        row = self._conn.execute(
            "SELECT * FROM archive_cache WHERE url = ? AND expires_at > ?",
            (url, now),
        ).fetchone()
        if row is None:
            return None
        return {
            "url": row["url"],
            "has_snapshot": bool(row["has_snapshot"]),
            "snapshot_url": row["snapshot_url"],
            "snapshot_timestamp": row["snapshot_timestamp"],
            "title": row["title"],
            "retry_count": row["retry_count"],
            "last_checked_at": row["last_checked_at"],
        }

    # ------------------------------------------------------------------
    # Pipeline Runs
    # ------------------------------------------------------------------

    def save_pipeline_run(
        self,
        run_id: str,
        target: str,
        last_node: str,
        state_json: str,
        status: str = "running",
    ) -> None:
        now = _now_iso()
        self._conn.execute(
            """INSERT OR REPLACE INTO pipeline_runs
            (run_id, target, last_node, state_json, started_at, updated_at, status)
            VALUES (?,?,?,?,COALESCE((SELECT started_at FROM pipeline_runs WHERE run_id = ?), ?),?,?)""",
            (run_id, target, last_node, state_json, run_id, now, now, status),
        )
        self._conn.commit()

    def load_pipeline_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "target": row["target"],
            "last_node": row["last_node"],
            "state_json": row["state_json"],
            "started_at": row["started_at"],
            "updated_at": row["updated_at"],
            "status": row["status"],
        }

    # ------------------------------------------------------------------
    # Repos
    # ------------------------------------------------------------------

    def upsert_repo(
        self,
        full_name: str,
        stars: int | None = None,
        contributors: int | None = None,
        pushed_at: str | None = None,
        has_contributing: bool = False,
        contributing_warnings: str | None = None,
    ) -> int:
        now = _now_iso()
        existing = self._conn.execute("SELECT id FROM repos WHERE full_name = ?", (full_name,)).fetchone()
        if existing:
            self._conn.execute(
                """UPDATE repos SET stars=COALESCE(?,stars), contributors=COALESCE(?,contributors),
                   pushed_at=COALESCE(?,pushed_at), has_contributing=?,
                   contributing_warnings=COALESCE(?,contributing_warnings), updated_at=?
                   WHERE id=?""",
                (stars, contributors, pushed_at, int(has_contributing), contributing_warnings, now, existing["id"]),
            )
            self._conn.commit()
            return existing["id"]
        else:
            cursor = self._conn.execute(
                """INSERT INTO repos
                (full_name, stars, contributors, pushed_at, has_contributing,
                 contributing_warnings, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (full_name, stars, contributors, pushed_at, int(has_contributing), contributing_warnings, now, now),
            )
            self._conn.commit()
            return cursor.lastrowid  # type: ignore[return-value]

    def get_repo(self, full_name: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM repos WHERE full_name = ?", (full_name,)).fetchone()
        if row is None:
            return None
        return dict(row)

    # ------------------------------------------------------------------
    # Scans
    # ------------------------------------------------------------------

    def record_scan(
        self,
        repo_id: int,
        run_id: str,
        started_at: str | None = None,
    ) -> int:
        now = started_at or _now_iso()
        cursor = self._conn.execute(
            "INSERT INTO scans (repo_id, run_id, started_at) VALUES (?,?,?)",
            (repo_id, run_id, now),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def complete_scan(
        self,
        scan_id: int,
        dead_links_found: int = 0,
        fixes_generated: int = 0,
        pr_submitted: int = 0,
        decision: str | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        now = _now_iso()
        self._conn.execute(
            """UPDATE scans SET completed_at=?, dead_links_found=?,
               fixes_generated=?, pr_submitted=?, decision=?, duration_seconds=?
               WHERE id=?""",
            (now, dead_links_found, fixes_generated, pr_submitted, decision, duration_seconds, scan_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Findings
    # ------------------------------------------------------------------

    def record_finding(
        self,
        scan_id: int,
        url: str,
        source_file: str,
        line_number: int | None = None,
        http_status: int | None = None,
        error_type: str | None = None,
        status: str = "pending",
        is_historical_file: bool = False,
    ) -> int:
        now = _now_iso()
        cursor = self._conn.execute(
            """INSERT INTO findings
            (scan_id, url, source_file, line_number, http_status, error_type,
             status, is_historical_file, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (scan_id, url, source_file, line_number, http_status, error_type, status, int(is_historical_file), now),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def update_finding_status(
        self,
        finding_id: int,
        status: str,
        replacement_url: str | None = None,
        confidence: float | None = None,
    ) -> None:
        parts = ["status = ?"]
        params: list[Any] = [status]
        if replacement_url is not None:
            parts.append("replacement_url = ?")
            params.append(replacement_url)
        if confidence is not None:
            parts.append("confidence = ?")
            params.append(confidence)
        params.append(finding_id)
        self._conn.execute(
            f"UPDATE findings SET {', '.join(parts)} WHERE id = ?",  # noqa: S608
            params,
        )
        self._conn.commit()


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_interaction(row: sqlite3.Row) -> InteractionRecord:
    return InteractionRecord(
        id=row["id"],
        repo_url=row["repo_url"],
        broken_url=row["broken_url"],
        status=InteractionStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        pr_url=row["pr_url"],
        maintainer=row["maintainer"],
        notes=row["notes"],
    )


def _row_to_blacklist(row: sqlite3.Row) -> BlacklistEntry:
    return BlacklistEntry(
        id=row["id"],
        repo_url=row["repo_url"],
        maintainer=row["maintainer"],
        reason=row["reason"],
        created_at=datetime.fromisoformat(row["created_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
    )
