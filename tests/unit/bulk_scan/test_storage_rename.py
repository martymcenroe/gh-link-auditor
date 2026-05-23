"""Tests for #250 — schema v8 + ``storage.apply_repo_rename``.

The migration adds ``bulk_scan_repos.previous_full_name TEXT NULL``. The
storage helper updates the PK and propagates the rename to ``bulk_scan_findings``
so finding rows stay linked.
"""

from __future__ import annotations

import sqlite3

from gh_link_auditor.bulk_scan import storage
from gh_link_auditor.unified_db import SCHEMA_VERSION, UnifiedDatabase

# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------


class TestSchemaV8AddsPreviousFullName:
    def test_fresh_db_has_previous_full_name_column(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            cols = {r[1] for r in db._conn.execute("PRAGMA table_info(bulk_scan_repos)")}
            assert "previous_full_name" in cols

    def test_schema_version_advances_to_8(self) -> None:
        assert SCHEMA_VERSION >= 8

    def test_migration_v7_to_v8_adds_column(self, tmp_path) -> None:
        """A pre-existing v7 DB (without previous_full_name) gets the column on next open."""
        db_path = str(tmp_path / "y.db")
        # Bootstrap a fresh DB then simulate a v7 state by dropping the column +
        # rolling back schema_version.
        with UnifiedDatabase(db_path):
            pass
        con = sqlite3.connect(db_path)
        con.execute("UPDATE schema_version SET version = 7")
        # SQLite has no native DROP COLUMN; recreate the table without it.
        con.executescript(
            """
            CREATE TABLE bulk_scan_repos_old AS SELECT
                run_id, repo_full_name, stars, pushed_at, status,
                doc_files_json, url_count, dead_url_count,
                surface_candidate_count, error, detected_language,
                updated_at
            FROM bulk_scan_repos;
            DROP TABLE bulk_scan_repos;
            CREATE TABLE bulk_scan_repos (
                run_id TEXT NOT NULL,
                repo_full_name TEXT NOT NULL,
                stars INTEGER,
                pushed_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                doc_files_json TEXT,
                url_count INTEGER DEFAULT 0,
                dead_url_count INTEGER DEFAULT 0,
                surface_candidate_count INTEGER DEFAULT 0,
                error TEXT,
                detected_language TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (run_id, repo_full_name)
            );
            INSERT INTO bulk_scan_repos SELECT * FROM bulk_scan_repos_old;
            DROP TABLE bulk_scan_repos_old;
            """
        )
        con.commit()
        con.close()

        # Re-open via UnifiedDatabase → v7→v8 migration runs.
        with UnifiedDatabase(db_path) as db:
            cols = {r[1] for r in db._conn.execute("PRAGMA table_info(bulk_scan_repos)")}
            assert "previous_full_name" in cols
            ver = db._conn.execute("SELECT version FROM schema_version").fetchone()[0]
            assert ver == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# storage.apply_repo_rename
# ---------------------------------------------------------------------------


class TestApplyRepoRename:
    def test_renames_existing_row_and_sets_previous_full_name(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 1, {})
            storage.upsert_repo(db, "r1", "old/name", stars=42)

            applied = storage.apply_repo_rename(db, "r1", "old/name", "new/name")
            assert applied is True

            row = db._conn.execute(
                "SELECT repo_full_name, previous_full_name, stars FROM bulk_scan_repos WHERE run_id = ?",
                ("r1",),
            ).fetchone()
            assert row["repo_full_name"] == "new/name"
            assert row["previous_full_name"] == "old/name"
            assert row["stars"] == 42  # other columns preserved

    def test_propagates_rename_to_findings(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 1, {})
            storage.upsert_repo(db, "r1", "old/name")
            storage.add_finding(
                db,
                "r1",
                "old/name",
                "README.md",
                1,
                "http://dead.example.com/",
                candidate_url="",
                method="pending",
                tier=0,
                similarity_score=None,
                verified_live=False,
                confidence=0.0,
            )

            assert storage.apply_repo_rename(db, "r1", "old/name", "new/name") is True

            rows = db._conn.execute(
                "SELECT repo_full_name FROM bulk_scan_findings WHERE run_id = ?",
                ("r1",),
            ).fetchall()
            assert {r["repo_full_name"] for r in rows} == {"new/name"}

    def test_collision_returns_false_and_leaves_data_intact(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 1, {})
            storage.upsert_repo(db, "r1", "old/name", stars=10)
            storage.upsert_repo(db, "r1", "new/name", stars=20)

            applied = storage.apply_repo_rename(db, "r1", "old/name", "new/name")
            assert applied is False

            # Both rows still exist with their original data.
            rows = {
                r["repo_full_name"]: r
                for r in db._conn.execute(
                    "SELECT repo_full_name, stars, previous_full_name FROM bulk_scan_repos WHERE run_id = ?",
                    ("r1",),
                ).fetchall()
            }
            assert set(rows) == {"old/name", "new/name"}
            assert rows["old/name"]["previous_full_name"] is None
            assert rows["new/name"]["previous_full_name"] is None

    def test_same_name_is_noop(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 1, {})
            storage.upsert_repo(db, "r1", "same/name")
            assert storage.apply_repo_rename(db, "r1", "same/name", "same/name") is False
            row = db._conn.execute(
                "SELECT previous_full_name FROM bulk_scan_repos WHERE run_id = ?",
                ("r1",),
            ).fetchone()
            assert row["previous_full_name"] is None


# ---------------------------------------------------------------------------
# Runner integration — the run_inventory loop calls apply_repo_rename
# ---------------------------------------------------------------------------


class TestRunInventoryHandlesRename:
    """Stage 1's run_inventory uses inventory_repo's renamed_from signal to
    update bulk_scan_repos atomically with the new name before recording
    findings (#250).
    """

    def test_rename_updates_repo_row_and_findings_use_new_name(self, tmp_path) -> None:
        from unittest.mock import patch

        from gh_link_auditor.bulk_scan import inventory, runner

        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 1, {})
            storage.upsert_repo(db, "r1", "old/name")

            fake_inventory_result = {
                "doc_files": ["README.md"],
                "urls": [("https://example.org/x", "README.md", 1)],
                "renamed_from": "old/name",
                "current_full_name": "new/name",
            }

            class _StubClient:
                def close(self) -> None:
                    return None

            with (
                patch.object(inventory, "inventory_repo", return_value=fake_inventory_result),
                patch.object(inventory, "build_api_client", return_value=_StubClient()),
                patch.object(inventory, "build_raw_client", return_value=_StubClient()),
            ):
                runner.run_inventory(db, "r1")

            row = db._conn.execute(
                "SELECT repo_full_name, previous_full_name, status FROM bulk_scan_repos WHERE run_id = ?",
                ("r1",),
            ).fetchone()
            assert row["repo_full_name"] == "new/name"
            assert row["previous_full_name"] == "old/name"
            assert row["status"] == "inventoried"

            findings = db._conn.execute(
                "SELECT repo_full_name, dead_url FROM bulk_scan_findings WHERE run_id = ?",
                ("r1",),
            ).fetchall()
            assert len(findings) == 1
            assert findings[0]["repo_full_name"] == "new/name"
            assert findings[0]["dead_url"] == "https://example.org/x"
