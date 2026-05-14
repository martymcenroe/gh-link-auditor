"""Tests for the rewrite_queue table and its UnifiedDatabase methods (#212)."""

from __future__ import annotations

from gh_link_auditor.unified_db import SCHEMA_VERSION, UnifiedDatabase


class TestSchemaVersion:
    def test_schema_version_is_4(self) -> None:
        assert SCHEMA_VERSION == 4

    def test_fresh_db_has_rewrite_queue_table(self, tmp_path) -> None:
        db_path = str(tmp_path / "rq.db")
        with UnifiedDatabase(db_path) as db:
            rows = db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='rewrite_queue'"
            ).fetchall()
            assert len(rows) == 1

    def test_fresh_db_records_schema_v4(self, tmp_path) -> None:
        db_path = str(tmp_path / "rq.db")
        with UnifiedDatabase(db_path) as db:
            row = db._conn.execute("SELECT version FROM schema_version").fetchone()
            assert row["version"] == 4


class TestAddToRewriteQueue:
    def test_returns_row_id(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "rq.db")) as db:
            rid = db.add_to_rewrite_queue(
                dead_url="https://dead.example/x",
                source_file="docs/a.rst",
                line_number=42,
                repo_full_name="o/r",
                reason="dead product",
            )
            assert rid == 1

    def test_persists_all_fields(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "rq.db")) as db:
            db.add_to_rewrite_queue(
                dead_url="https://dead.example/x",
                source_file="docs/a.rst",
                line_number=42,
                repo_full_name="o/r",
                reason="dead product",
            )
            row = db._conn.execute("SELECT * FROM rewrite_queue WHERE id=1").fetchone()
            assert row["dead_url"] == "https://dead.example/x"
            assert row["source_file"] == "docs/a.rst"
            assert row["line_number"] == 42
            assert row["repo_full_name"] == "o/r"
            assert row["reason"] == "dead product"
            assert row["added_at"] is not None
            assert row["exported_to_issue"] is None

    def test_reason_defaults_to_null(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "rq.db")) as db:
            db.add_to_rewrite_queue(
                dead_url="https://dead.example/x",
                source_file="docs/a.rst",
                line_number=None,
                repo_full_name="o/r",
            )
            row = db._conn.execute("SELECT * FROM rewrite_queue WHERE id=1").fetchone()
            assert row["reason"] is None
            assert row["line_number"] is None

    def test_multiple_inserts_get_distinct_ids(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "rq.db")) as db:
            id1 = db.add_to_rewrite_queue("u1", "f", 1, "o/r")
            id2 = db.add_to_rewrite_queue("u2", "f", 2, "o/r")
            assert id2 == id1 + 1


class TestGetRewriteQueue:
    def test_empty_returns_empty_list(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "rq.db")) as db:
            assert db.get_rewrite_queue() == []

    def test_filters_by_repo(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "rq.db")) as db:
            db.add_to_rewrite_queue("u1", "f", 1, "a/b")
            db.add_to_rewrite_queue("u2", "f", 2, "c/d")
            ab = db.get_rewrite_queue("a/b")
            assert len(ab) == 1
            assert ab[0]["dead_url"] == "u1"

    def test_returns_all_when_no_repo_filter(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "rq.db")) as db:
            db.add_to_rewrite_queue("u1", "f", 1, "a/b")
            db.add_to_rewrite_queue("u2", "f", 2, "c/d")
            assert len(db.get_rewrite_queue()) == 2

    def test_excludes_exported_by_default(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "rq.db")) as db:
            db.add_to_rewrite_queue("u1", "f", 1, "a/b")
            db.add_to_rewrite_queue("u2", "f", 2, "a/b")
            db.mark_rewrite_queue_exported("a/b", 99)
            db.add_to_rewrite_queue("u3", "f", 3, "a/b")  # new, unexported
            pending = db.get_rewrite_queue("a/b")
            assert len(pending) == 1
            assert pending[0]["dead_url"] == "u3"

    def test_include_exported_returns_everything(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "rq.db")) as db:
            db.add_to_rewrite_queue("u1", "f", 1, "a/b")
            db.mark_rewrite_queue_exported("a/b", 99)
            db.add_to_rewrite_queue("u2", "f", 2, "a/b")
            all_rows = db.get_rewrite_queue("a/b", include_exported=True)
            assert len(all_rows) == 2

    def test_ordered_newest_first(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "rq.db")) as db:
            db.add_to_rewrite_queue("u1", "f", 1, "a/b")
            db.add_to_rewrite_queue("u2", "f", 2, "a/b")
            rows = db.get_rewrite_queue("a/b")
            # newer (u2) first
            assert rows[0]["dead_url"] == "u2"
            assert rows[1]["dead_url"] == "u1"


class TestMarkRewriteQueueExported:
    def test_marks_pending_entries(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "rq.db")) as db:
            db.add_to_rewrite_queue("u1", "f", 1, "a/b")
            db.add_to_rewrite_queue("u2", "f", 2, "a/b")
            count = db.mark_rewrite_queue_exported("a/b", 42)
            assert count == 2
            for row in db.get_rewrite_queue("a/b", include_exported=True):
                assert row["exported_to_issue"] == 42

    def test_skips_already_exported(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "rq.db")) as db:
            db.add_to_rewrite_queue("u1", "f", 1, "a/b")
            db.mark_rewrite_queue_exported("a/b", 1)
            db.add_to_rewrite_queue("u2", "f", 2, "a/b")
            count = db.mark_rewrite_queue_exported("a/b", 2)
            assert count == 1  # only u2 was newly marked

    def test_filters_by_repo(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "rq.db")) as db:
            db.add_to_rewrite_queue("u1", "f", 1, "a/b")
            db.add_to_rewrite_queue("u2", "f", 2, "c/d")
            count = db.mark_rewrite_queue_exported("a/b", 99)
            assert count == 1

    def test_returns_zero_when_no_pending(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "rq.db")) as db:
            assert db.mark_rewrite_queue_exported("a/b", 1) == 0


class TestClearRewriteQueue:
    def test_deletes_all_for_repo(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "rq.db")) as db:
            db.add_to_rewrite_queue("u1", "f", 1, "a/b")
            db.add_to_rewrite_queue("u2", "f", 2, "a/b")
            db.add_to_rewrite_queue("u3", "f", 3, "c/d")
            count = db.clear_rewrite_queue("a/b")
            assert count == 2
            assert db.get_rewrite_queue("a/b") == []
            assert len(db.get_rewrite_queue("c/d")) == 1

    def test_returns_zero_when_no_entries(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "rq.db")) as db:
            assert db.clear_rewrite_queue("a/b") == 0

    def test_includes_exported_in_delete(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "rq.db")) as db:
            db.add_to_rewrite_queue("u1", "f", 1, "a/b")
            db.mark_rewrite_queue_exported("a/b", 1)
            db.add_to_rewrite_queue("u2", "f", 2, "a/b")
            count = db.clear_rewrite_queue("a/b")
            assert count == 2  # both exported and pending


class TestMigrationV3ToV4:
    """Ensure a v3 DB upgrades cleanly on first open."""

    def test_v3_db_gains_rewrite_queue(self, tmp_path) -> None:
        import sqlite3

        db_path = str(tmp_path / "v3.db")
        # Create a minimal v3-shaped DB by hand
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version (version) VALUES (3)")
        conn.commit()
        conn.close()

        # Open via UnifiedDatabase — should trigger migration
        with UnifiedDatabase(db_path) as db:
            row = db._conn.execute("SELECT version FROM schema_version").fetchone()
            assert row["version"] == 4
            tables = db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='rewrite_queue'"
            ).fetchall()
            assert len(tables) == 1
