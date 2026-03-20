"""Tests for snooze/recheck functionality in unified_db.

Tests cover schema v3 migration, snooze_finding, get_due_rechecks,
complete_recheck, increment_recheck, and get_recheck_stats.

See issue #148 for specification.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from gh_link_auditor.unified_db import SCHEMA_VERSION, UnifiedDatabase

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    with UnifiedDatabase(":memory:") as database:
        yield database


# ---------------------------------------------------------------------------
# Schema v3
# ---------------------------------------------------------------------------


class TestSchemaV3:
    """Tests for schema version 3 and recheck_queue columns."""

    def test_schema_version_is_3(self, db) -> None:
        row = db._conn.execute("SELECT version FROM schema_version").fetchone()
        assert row["version"] == 3

    def test_schema_version_constant(self) -> None:
        assert SCHEMA_VERSION == 3

    def test_recheck_queue_has_url_column(self, db) -> None:
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(recheck_queue)").fetchall()}
        assert "url" in cols

    def test_recheck_queue_has_repo_full_name_column(self, db) -> None:
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(recheck_queue)").fetchall()}
        assert "repo_full_name" in cols

    def test_recheck_queue_has_source_file_column(self, db) -> None:
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(recheck_queue)").fetchall()}
        assert "source_file" in cols

    def test_recheck_queue_has_recheck_count_column(self, db) -> None:
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(recheck_queue)").fetchall()}
        assert "recheck_count" in cols

    def test_recheck_queue_has_last_status_column(self, db) -> None:
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(recheck_queue)").fetchall()}
        assert "last_status" in cols

    def test_recheck_queue_has_last_checked_at_column(self, db) -> None:
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(recheck_queue)").fetchall()}
        assert "last_checked_at" in cols

    def test_recheck_queue_all_columns(self, db) -> None:
        """All expected columns exist in recheck_queue."""
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(recheck_queue)").fetchall()}
        expected = {
            "id",
            "finding_id",
            "url",
            "repo_full_name",
            "source_file",
            "recheck_count",
            "last_status",
            "last_checked_at",
            "snooze_until",
            "reason",
            "created_at",
        }
        assert expected.issubset(cols)


class TestMigrationV2ToV3:
    """Tests for the v2 to v3 migration path."""

    def test_migration_adds_columns_to_v2_table(self) -> None:
        """Simulate a v2 database and verify migration adds new columns."""
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version (version) VALUES (2)")

        # Create v2-style recheck_queue (without new columns)
        conn.execute("""
            CREATE TABLE recheck_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                finding_id INTEGER,
                snooze_until TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # Create minimal required tables so bootstrap doesn't fail
        conn.execute("CREATE TABLE interactions (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE blacklist (id INTEGER PRIMARY KEY, source TEXT DEFAULT 'manual')")
        conn.commit()
        conn.close()

        # Now open via UnifiedDatabase which should trigger migration
        # We need a file path since :memory: won't work across connections
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "test.db")

            # Create v2 database on disk
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
            conn.execute("INSERT INTO schema_version (version) VALUES (2)")
            conn.execute("""
                CREATE TABLE recheck_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    finding_id INTEGER,
                    snooze_until TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE TABLE interactions (id INTEGER PRIMARY KEY)")
            conn.execute("CREATE TABLE blacklist (id INTEGER PRIMARY KEY, source TEXT DEFAULT 'manual')")
            conn.commit()
            conn.close()

            # Open with UnifiedDatabase -- should migrate v2 -> v3
            with UnifiedDatabase(db_path) as db:
                cols = {row[1] for row in db._conn.execute("PRAGMA table_info(recheck_queue)").fetchall()}
                assert "url" in cols
                assert "repo_full_name" in cols
                assert "source_file" in cols
                assert "recheck_count" in cols
                assert "last_status" in cols
                assert "last_checked_at" in cols

                # Verify version is bumped
                row = db._conn.execute("SELECT version FROM schema_version").fetchone()
                assert row["version"] == 3

    def test_migration_idempotent_when_columns_exist(self) -> None:
        """Migration should not fail if columns already exist (fresh v3 install)."""
        # A fresh :memory: db already has all columns.
        # Manually trigger migration on it should not fail.
        with UnifiedDatabase(":memory:") as db:
            # Force re-migrate (simulate calling _migrate_v2_to_v3 on already-v3 db)
            db._migrate_v2_to_v3()
            cols = {row[1] for row in db._conn.execute("PRAGMA table_info(recheck_queue)").fetchall()}
            assert "url" in cols
            assert "repo_full_name" in cols


# ---------------------------------------------------------------------------
# snooze_finding
# ---------------------------------------------------------------------------


class TestSnoozeFinding:
    """Tests for UnifiedDatabase.snooze_finding()."""

    def test_returns_entry_id(self, db) -> None:
        entry_id = db.snooze_finding(
            url="https://example.com/dead",
            repo_full_name="owner/repo",
            source_file="README.md",
        )
        assert isinstance(entry_id, int)
        assert entry_id > 0

    def test_stores_url(self, db) -> None:
        db.snooze_finding(
            url="https://example.com/dead",
            repo_full_name="owner/repo",
            source_file="README.md",
        )
        row = db._conn.execute("SELECT url FROM recheck_queue").fetchone()
        assert row["url"] == "https://example.com/dead"

    def test_stores_repo_full_name(self, db) -> None:
        db.snooze_finding(
            url="https://example.com/dead",
            repo_full_name="owner/repo",
            source_file="README.md",
        )
        row = db._conn.execute("SELECT repo_full_name FROM recheck_queue").fetchone()
        assert row["repo_full_name"] == "owner/repo"

    def test_stores_source_file(self, db) -> None:
        db.snooze_finding(
            url="https://example.com/dead",
            repo_full_name="owner/repo",
            source_file="docs/guide.md",
        )
        row = db._conn.execute("SELECT source_file FROM recheck_queue").fetchone()
        assert row["source_file"] == "docs/guide.md"

    def test_default_snooze_days_7(self, db) -> None:
        db.snooze_finding(
            url="https://example.com/dead",
            repo_full_name="owner/repo",
            source_file="README.md",
        )
        row = db._conn.execute("SELECT snooze_until FROM recheck_queue").fetchone()
        snooze_until = datetime.fromisoformat(row["snooze_until"])
        now = datetime.now(timezone.utc)
        # Should be approximately 7 days from now
        diff = snooze_until - now
        assert 6 < diff.total_seconds() / 86400 < 8

    def test_custom_snooze_days(self, db) -> None:
        db.snooze_finding(
            url="https://example.com/dead",
            repo_full_name="owner/repo",
            source_file="README.md",
            snooze_days=14,
        )
        row = db._conn.execute("SELECT snooze_until FROM recheck_queue").fetchone()
        snooze_until = datetime.fromisoformat(row["snooze_until"])
        now = datetime.now(timezone.utc)
        diff = snooze_until - now
        assert 13 < diff.total_seconds() / 86400 < 15

    def test_stores_reason(self, db) -> None:
        db.snooze_finding(
            url="https://example.com/dead",
            repo_full_name="owner/repo",
            source_file="README.md",
            reason="Might come back",
        )
        row = db._conn.execute("SELECT reason FROM recheck_queue").fetchone()
        assert row["reason"] == "Might come back"

    def test_default_reason_none(self, db) -> None:
        db.snooze_finding(
            url="https://example.com/dead",
            repo_full_name="owner/repo",
            source_file="README.md",
        )
        row = db._conn.execute("SELECT reason FROM recheck_queue").fetchone()
        assert row["reason"] is None

    def test_initial_recheck_count_zero(self, db) -> None:
        db.snooze_finding(
            url="https://example.com/dead",
            repo_full_name="owner/repo",
            source_file="README.md",
        )
        row = db._conn.execute("SELECT recheck_count FROM recheck_queue").fetchone()
        assert row["recheck_count"] == 0

    def test_initial_last_status_snoozed(self, db) -> None:
        db.snooze_finding(
            url="https://example.com/dead",
            repo_full_name="owner/repo",
            source_file="README.md",
        )
        row = db._conn.execute("SELECT last_status FROM recheck_queue").fetchone()
        assert row["last_status"] == "snoozed"

    def test_multiple_snoozes(self, db) -> None:
        id1 = db.snooze_finding(url="https://a.com", repo_full_name="o/r", source_file="f1.md")
        id2 = db.snooze_finding(url="https://b.com", repo_full_name="o/r", source_file="f2.md")
        assert id1 != id2
        count = db._conn.execute("SELECT COUNT(*) AS cnt FROM recheck_queue").fetchone()
        assert count["cnt"] == 2


# ---------------------------------------------------------------------------
# get_due_rechecks
# ---------------------------------------------------------------------------


class TestGetDueRechecks:
    """Tests for UnifiedDatabase.get_due_rechecks()."""

    def test_empty_queue(self, db) -> None:
        assert db.get_due_rechecks() == []

    def test_returns_due_entries(self, db) -> None:
        # Insert an entry with snooze_until in the past
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        db._conn.execute(
            """INSERT INTO recheck_queue
            (url, repo_full_name, source_file, recheck_count, last_status,
             last_checked_at, snooze_until, reason, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            ("https://example.com/dead", "o/r", "README.md", 0, "snoozed", past, past, None, past),
        )
        db._conn.commit()

        due = db.get_due_rechecks()
        assert len(due) == 1
        assert due[0]["url"] == "https://example.com/dead"

    def test_excludes_future_entries(self, db) -> None:
        future = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        past = datetime.now(timezone.utc).isoformat()
        db._conn.execute(
            """INSERT INTO recheck_queue
            (url, repo_full_name, source_file, recheck_count, last_status,
             last_checked_at, snooze_until, reason, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            ("https://example.com/dead", "o/r", "README.md", 0, "snoozed", past, future, None, past),
        )
        db._conn.commit()

        assert db.get_due_rechecks() == []

    def test_excludes_resolved(self, db) -> None:
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        db._conn.execute(
            """INSERT INTO recheck_queue
            (url, repo_full_name, source_file, recheck_count, last_status,
             last_checked_at, snooze_until, reason, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            ("https://example.com/dead", "o/r", "README.md", 0, "resolved", past, past, None, past),
        )
        db._conn.commit()

        assert db.get_due_rechecks() == []

    def test_excludes_confirmed_dead(self, db) -> None:
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        db._conn.execute(
            """INSERT INTO recheck_queue
            (url, repo_full_name, source_file, recheck_count, last_status,
             last_checked_at, snooze_until, reason, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                "https://example.com/dead",
                "o/r",
                "README.md",
                3,
                "confirmed_dead",
                past,
                past,
                None,
                past,
            ),
        )
        db._conn.commit()

        assert db.get_due_rechecks() == []

    def test_returns_dict_with_all_fields(self, db) -> None:
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        db._conn.execute(
            """INSERT INTO recheck_queue
            (url, repo_full_name, source_file, recheck_count, last_status,
             last_checked_at, snooze_until, reason, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            ("https://example.com/dead", "o/r", "README.md", 1, "snoozed", past, past, "test", past),
        )
        db._conn.commit()

        due = db.get_due_rechecks()
        assert len(due) == 1
        entry = due[0]
        assert "id" in entry
        assert entry["url"] == "https://example.com/dead"
        assert entry["repo_full_name"] == "o/r"
        assert entry["source_file"] == "README.md"
        assert entry["recheck_count"] == 1
        assert entry["last_status"] == "snoozed"
        assert entry["reason"] == "test"

    def test_ordered_by_snooze_until(self, db) -> None:
        past1 = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        past2 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        for url, past in [("https://b.com", past2), ("https://a.com", past1)]:
            db._conn.execute(
                """INSERT INTO recheck_queue
                (url, repo_full_name, source_file, recheck_count, last_status,
                 last_checked_at, snooze_until, reason, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (url, "o/r", "README.md", 0, "snoozed", past, past, None, past),
            )
        db._conn.commit()

        due = db.get_due_rechecks()
        assert due[0]["url"] == "https://a.com"  # Earlier snooze_until first
        assert due[1]["url"] == "https://b.com"


# ---------------------------------------------------------------------------
# complete_recheck
# ---------------------------------------------------------------------------


class TestCompleteRecheck:
    """Tests for UnifiedDatabase.complete_recheck()."""

    def test_marks_resolved(self, db) -> None:
        entry_id = db.snooze_finding(url="https://a.com", repo_full_name="o/r", source_file="f.md")
        db.complete_recheck(entry_id, "resolved")
        row = db._conn.execute("SELECT last_status FROM recheck_queue WHERE id = ?", (entry_id,)).fetchone()
        assert row["last_status"] == "resolved"

    def test_marks_confirmed_dead(self, db) -> None:
        entry_id = db.snooze_finding(url="https://a.com", repo_full_name="o/r", source_file="f.md")
        db.complete_recheck(entry_id, "confirmed_dead")
        row = db._conn.execute("SELECT last_status FROM recheck_queue WHERE id = ?", (entry_id,)).fetchone()
        assert row["last_status"] == "confirmed_dead"

    def test_updates_last_checked_at(self, db) -> None:
        entry_id = db.snooze_finding(url="https://a.com", repo_full_name="o/r", source_file="f.md")
        before = db._conn.execute("SELECT last_checked_at FROM recheck_queue WHERE id = ?", (entry_id,)).fetchone()[
            "last_checked_at"
        ]

        db.complete_recheck(entry_id, "resolved")

        after = db._conn.execute("SELECT last_checked_at FROM recheck_queue WHERE id = ?", (entry_id,)).fetchone()[
            "last_checked_at"
        ]
        assert after >= before


# ---------------------------------------------------------------------------
# increment_recheck
# ---------------------------------------------------------------------------


class TestIncrementRecheck:
    """Tests for UnifiedDatabase.increment_recheck()."""

    def test_increments_count(self, db) -> None:
        entry_id = db.snooze_finding(url="https://a.com", repo_full_name="o/r", source_file="f.md")
        db.increment_recheck(entry_id)
        row = db._conn.execute("SELECT recheck_count FROM recheck_queue WHERE id = ?", (entry_id,)).fetchone()
        assert row["recheck_count"] == 1

    def test_double_increment(self, db) -> None:
        entry_id = db.snooze_finding(url="https://a.com", repo_full_name="o/r", source_file="f.md")
        db.increment_recheck(entry_id)
        db.increment_recheck(entry_id)
        row = db._conn.execute("SELECT recheck_count FROM recheck_queue WHERE id = ?", (entry_id,)).fetchone()
        assert row["recheck_count"] == 2

    def test_re_snoozes_7_days(self, db) -> None:
        entry_id = db.snooze_finding(url="https://a.com", repo_full_name="o/r", source_file="f.md")
        db.increment_recheck(entry_id, snooze_days=7)
        row = db._conn.execute("SELECT snooze_until FROM recheck_queue WHERE id = ?", (entry_id,)).fetchone()
        snooze_until = datetime.fromisoformat(row["snooze_until"])
        now = datetime.now(timezone.utc)
        diff = snooze_until - now
        assert 6 < diff.total_seconds() / 86400 < 8

    def test_resets_status_to_snoozed(self, db) -> None:
        entry_id = db.snooze_finding(url="https://a.com", repo_full_name="o/r", source_file="f.md")
        db.increment_recheck(entry_id)
        row = db._conn.execute("SELECT last_status FROM recheck_queue WHERE id = ?", (entry_id,)).fetchone()
        assert row["last_status"] == "snoozed"

    def test_custom_snooze_days(self, db) -> None:
        entry_id = db.snooze_finding(url="https://a.com", repo_full_name="o/r", source_file="f.md")
        db.increment_recheck(entry_id, snooze_days=14)
        row = db._conn.execute("SELECT snooze_until FROM recheck_queue WHERE id = ?", (entry_id,)).fetchone()
        snooze_until = datetime.fromisoformat(row["snooze_until"])
        now = datetime.now(timezone.utc)
        diff = snooze_until - now
        assert 13 < diff.total_seconds() / 86400 < 15


# ---------------------------------------------------------------------------
# get_recheck_stats
# ---------------------------------------------------------------------------


class TestGetRecheckStats:
    """Tests for UnifiedDatabase.get_recheck_stats()."""

    def test_empty_queue(self, db) -> None:
        stats = db.get_recheck_stats()
        assert stats == {"pending": 0, "resolved": 0, "confirmed_dead": 0}

    def test_counts_snoozed_as_pending(self, db) -> None:
        db.snooze_finding(url="https://a.com", repo_full_name="o/r", source_file="f.md")
        db.snooze_finding(url="https://b.com", repo_full_name="o/r", source_file="f.md")
        stats = db.get_recheck_stats()
        assert stats["pending"] == 2

    def test_counts_resolved(self, db) -> None:
        entry_id = db.snooze_finding(url="https://a.com", repo_full_name="o/r", source_file="f.md")
        db.complete_recheck(entry_id, "resolved")
        stats = db.get_recheck_stats()
        assert stats["resolved"] == 1
        assert stats["pending"] == 0

    def test_counts_confirmed_dead(self, db) -> None:
        entry_id = db.snooze_finding(url="https://a.com", repo_full_name="o/r", source_file="f.md")
        db.complete_recheck(entry_id, "confirmed_dead")
        stats = db.get_recheck_stats()
        assert stats["confirmed_dead"] == 1

    def test_mixed_statuses(self, db) -> None:
        id1 = db.snooze_finding(url="https://a.com", repo_full_name="o/r", source_file="f.md")
        id2 = db.snooze_finding(url="https://b.com", repo_full_name="o/r", source_file="f.md")
        db.snooze_finding(url="https://c.com", repo_full_name="o/r", source_file="f.md")
        db.complete_recheck(id1, "resolved")
        db.complete_recheck(id2, "confirmed_dead")
        stats = db.get_recheck_stats()
        assert stats["pending"] == 1
        assert stats["resolved"] == 1
        assert stats["confirmed_dead"] == 1
