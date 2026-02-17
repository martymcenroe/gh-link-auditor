"""Core database module with StateDatabase class.

Implements SQLite-based state tracking for bot interactions and maintainer blacklists.
See LLD Issue #5 for full specification.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from gh_link_auditor.models import BlacklistEntry, InteractionRecord, InteractionStatus


class StateDatabase:
    """SQLite-based state database for tracking bot interactions."""

    SCHEMA_VERSION = 1

    def __init__(self, db_path: str = "state.db") -> None:
        """Initialize database connection and create tables if needed.

        Args:
            db_path: Path to SQLite database file. Use ":memory:" for testing.
        """
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        # Enable WAL mode for durability
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self) -> None:
        """Create database tables and indexes if they don't exist."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER NOT NULL
                )
                """
            )
            # Seed schema version if empty
            row = self._conn.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (self.SCHEMA_VERSION,),
                )

            self._conn.execute(
                """
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
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_interactions_repo_url
                ON interactions (repo_url, broken_url)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_interactions_maintainer
                ON interactions (maintainer)
                """
            )

            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS blacklist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_url TEXT,
                    maintainer TEXT,
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    expires_at TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_blacklist_repo
                ON blacklist (repo_url)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_blacklist_maintainer
                ON blacklist (maintainer)
                """
            )

    def close(self) -> None:
        """Close database connection."""
        self._conn.close()

    def __enter__(self) -> StateDatabase:
        """Support context manager usage."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Close on context manager exit."""
        self.close()

    # -------------------------------------------------------------------------
    # Interaction Management
    # -------------------------------------------------------------------------

    def record_interaction(
        self,
        repo_url: str,
        broken_url: str,
        status: InteractionStatus,
        pr_url: str | None = None,
        maintainer: str | None = None,
        notes: str | None = None,
    ) -> int:
        """Record a new interaction. Returns the record ID."""
        now = _now_iso()
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO interactions
                    (repo_url, broken_url, status, created_at, updated_at,
                     pr_url, maintainer, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    repo_url,
                    broken_url,
                    status.value,
                    now,
                    now,
                    pr_url,
                    maintainer,
                    notes,
                ),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def update_interaction_status(
        self,
        record_id: int,
        new_status: InteractionStatus,
        pr_url: str | None = None,
        notes: str | None = None,
    ) -> bool:
        """Update status of an existing interaction. Returns success."""
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
        set_clause = ", ".join(parts)

        with self._conn:
            cursor = self._conn.execute(
                f"UPDATE interactions SET {set_clause} WHERE id = ?",  # noqa: S608
                params,
            )
            return cursor.rowcount > 0

    def get_interaction(
        self,
        repo_url: str,
        broken_url: str,
    ) -> InteractionRecord | None:
        """Get interaction record for a specific repo/URL combo."""
        row = self._conn.execute(
            """
            SELECT id, repo_url, broken_url, status, created_at, updated_at,
                   pr_url, maintainer, notes
            FROM interactions
            WHERE repo_url = ? AND broken_url = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (repo_url, broken_url),
        ).fetchone()

        if row is None:
            return None
        return _row_to_interaction(row)

    def has_been_submitted(
        self,
        repo_url: str,
        broken_url: str,
    ) -> bool:
        """Check if a fix has already been submitted for this URL."""
        row = self._conn.execute(
            """
            SELECT 1 FROM interactions
            WHERE repo_url = ? AND broken_url = ?
            LIMIT 1
            """,
            (repo_url, broken_url),
        ).fetchone()
        return row is not None

    # -------------------------------------------------------------------------
    # Blacklist Management
    # -------------------------------------------------------------------------

    def add_to_blacklist(
        self,
        repo_url: str | None = None,
        maintainer: str | None = None,
        reason: str = "",
        expires_at: datetime | None = None,
    ) -> int:
        """Add repo or maintainer to blacklist. Returns entry ID."""
        if repo_url is None and maintainer is None:
            raise ValueError("At least one of repo_url or maintainer must be provided")

        now = _now_iso()
        expires_str = expires_at.isoformat() if expires_at is not None else None

        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO blacklist (repo_url, maintainer, reason, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (repo_url, maintainer, reason, now, expires_str),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def remove_from_blacklist(
        self,
        entry_id: int,
    ) -> bool:
        """Remove entry from blacklist. Returns success."""
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM blacklist WHERE id = ?",
                (entry_id,),
            )
            return cursor.rowcount > 0

    def is_blacklisted(
        self,
        repo_url: str,
        maintainer: str | None = None,
    ) -> bool:
        """Check if repo or maintainer is blacklisted.

        Checks for:
        - Exact repo_url match in blacklist
        - Maintainer-level blacklist (if maintainer provided)
        Expired entries are ignored.
        """
        now = _now_iso()

        # Check repo-level blacklist
        row = self._conn.execute(
            """
            SELECT 1 FROM blacklist
            WHERE repo_url = ?
              AND (expires_at IS NULL OR expires_at > ?)
            LIMIT 1
            """,
            (repo_url, now),
        ).fetchone()
        if row is not None:
            return True

        # Check maintainer-level blacklist
        if maintainer is not None:
            row = self._conn.execute(
                """
                SELECT 1 FROM blacklist
                WHERE maintainer = ?
                  AND (expires_at IS NULL OR expires_at > ?)
                LIMIT 1
                """,
                (maintainer, now),
            ).fetchone()
            if row is not None:
                return True

        return False

    def get_blacklist(self) -> list[BlacklistEntry]:
        """Get all active (non-expired) blacklist entries."""
        now = _now_iso()
        rows = self._conn.execute(
            """
            SELECT id, repo_url, maintainer, reason, created_at, expires_at
            FROM blacklist
            WHERE expires_at IS NULL OR expires_at > ?
            ORDER BY created_at DESC
            """,
            (now,),
        ).fetchall()
        return [_row_to_blacklist(r) for r in rows]

    # -------------------------------------------------------------------------
    # Query Helpers
    # -------------------------------------------------------------------------

    def can_submit_fix(
        self,
        repo_url: str,
        broken_url: str,
        maintainer: str | None = None,
    ) -> tuple[bool, str]:
        """Master check before any bot action.

        Returns (can_submit, reason) tuple.
        """
        # Check blacklist first
        if self.is_blacklisted(repo_url, maintainer):
            return (False, "blacklisted")

        # Check for duplicates
        if self.has_been_submitted(repo_url, broken_url):
            return (False, "already submitted")

        return (True, "ok")

    def get_stats(self) -> dict[str, Any]:
        """Get summary statistics of all interactions."""
        stats: dict[str, Any] = {}

        # Total interactions
        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM interactions"
        ).fetchone()
        stats["total_interactions"] = row["cnt"]

        # Counts by status
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM interactions GROUP BY status"
        ).fetchall()
        by_status: dict[str, int] = {}
        for r in rows:
            by_status[r["status"]] = r["cnt"]
        stats["by_status"] = by_status

        # Active blacklist entries
        now = _now_iso()
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM blacklist
            WHERE expires_at IS NULL OR expires_at > ?
            """,
            (now,),
        ).fetchone()
        stats["active_blacklist_entries"] = row["cnt"]

        # Total blacklist entries (including expired)
        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM blacklist"
        ).fetchone()
        stats["total_blacklist_entries"] = row["cnt"]

        return stats


# -----------------------------------------------------------------------------
# Private helpers
# -----------------------------------------------------------------------------


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _row_to_interaction(row: sqlite3.Row) -> InteractionRecord:
    """Convert a database row to an InteractionRecord."""
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
    """Convert a database row to a BlacklistEntry."""
    return BlacklistEntry(
        id=row["id"],
        repo_url=row["repo_url"],
        maintainer=row["maintainer"],
        reason=row["reason"],
        created_at=datetime.fromisoformat(row["created_at"]),
        expires_at=(
            datetime.fromisoformat(row["expires_at"])
            if row["expires_at"] is not None
            else None
        ),
    )
