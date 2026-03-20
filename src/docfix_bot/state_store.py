"""SQLite-backed state store for Doc-Fix Bot.

Replaces TinyDB with UnifiedDatabase while preserving the same API.
See LLD #2 §2.4 for state_store specification.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from docfix_bot.models import PRSubmission, TargetRepository

logger = logging.getLogger(__name__)


class StateStore:
    """SQLite-backed state store for Doc-Fix Bot."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        with self._conn:
            self._conn.execute("""
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
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_submissions_repo ON submissions (repo_owner, repo_name)")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS api_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL
                )
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL,
                    repo TEXT NOT NULL,
                    scan_time TEXT NOT NULL
                )
            """)
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_scans_repo ON scans (owner, repo)")

    def record_pr_submission(self, submission: PRSubmission) -> None:
        repo = submission["repository"]
        links = [dict(bl) for bl in submission["broken_links_fixed"]]
        self._conn.execute(
            """INSERT INTO submissions
            (repo_owner, repo_name, branch_name, pr_number, pr_url, status,
             broken_links_json, submitted_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                repo["owner"],
                repo["repo"],
                submission.get("branch_name"),
                submission.get("pr_number"),
                submission.get("pr_url"),
                submission.get("status"),
                json.dumps(links),
                submission.get("submitted_at", datetime.now(timezone.utc).isoformat()),
            ),
        )
        self._conn.commit()

    def was_link_already_fixed(self, target: TargetRepository, url: str) -> bool:
        rows = self._conn.execute(
            "SELECT broken_links_json FROM submissions WHERE repo_owner = ? AND repo_name = ?",
            (target["owner"], target["repo"]),
        ).fetchall()
        for row in rows:
            links = json.loads(row["broken_links_json"]) if row["broken_links_json"] else []
            for link in links:
                if link.get("original_url") == url:
                    return True
        return False

    def get_daily_pr_count(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM submissions WHERE submitted_at LIKE ?",
            (f"{today}%",),
        ).fetchone()
        return row["cnt"]

    def get_hourly_api_count(self) -> int:
        hour_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM api_calls WHERE timestamp LIKE ?",
            (f"{hour_prefix}%",),
        ).fetchone()
        return row["cnt"]

    def increment_api_count(self) -> None:
        self._conn.execute(
            "INSERT INTO api_calls (timestamp) VALUES (?)",
            (datetime.now(timezone.utc).isoformat(),),
        )
        self._conn.commit()

    def record_scan(self, target: TargetRepository, scan_time: str) -> None:
        self._conn.execute(
            "INSERT INTO scans (owner, repo, scan_time) VALUES (?,?,?)",
            (target["owner"], target["repo"], scan_time),
        )
        self._conn.commit()

    def was_recently_scanned(self, target: TargetRepository, hours: int = 24) -> bool:
        rows = self._conn.execute(
            "SELECT scan_time FROM scans WHERE owner = ? AND repo = ? ORDER BY scan_time DESC LIMIT 1",
            (target["owner"], target["repo"]),
        ).fetchall()
        if not rows:
            return False
        scan_dt = datetime.fromisoformat(rows[0]["scan_time"])
        now = datetime.now(timezone.utc)
        return (now - scan_dt).total_seconds() < hours * 3600

    def close(self) -> None:
        self._conn.close()
