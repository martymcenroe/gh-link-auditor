"""Tests for bulk_scan.storage (#218)."""

from __future__ import annotations

from gh_link_auditor.bulk_scan import storage
from gh_link_auditor.unified_db import SCHEMA_VERSION, UnifiedDatabase


class TestSchemaV5:
    def test_schema_version(self) -> None:
        assert SCHEMA_VERSION == 5

    def test_fresh_db_has_bulk_scan_tables(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            tables = {
                r["name"] for r in db._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            assert "bulk_scan_runs" in tables
            assert "bulk_scan_repos" in tables
            assert "bulk_scan_findings" in tables


class TestRunLifecycle:
    def test_create_and_get(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 100, {"foo": "bar"})
            run = storage.get_run(db, "r1")
            assert run is not None
            assert run["run_id"] == "r1"
            assert run["status"] == "selecting"
            assert run["target_repo_count"] == 100

    def test_update_status(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 10, {})
            storage.update_run_status(db, "r1", "inventorying")
            assert storage.get_run(db, "r1")["status"] == "inventorying"

    def test_terminal_status_sets_completed(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 10, {})
            storage.update_run_status(db, "r1", "done")
            assert storage.get_run(db, "r1")["completed_at"] is not None

    def test_quality_aborted_flag(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 10, {})
            storage.update_run_status(db, "r1", "quality_aborted", quality_aborted=True)
            run = storage.get_run(db, "r1")
            assert run["status"] == "quality_aborted"
            assert run["quality_aborted"] == 1

    def test_list_runs_newest_first(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 1, {})
            storage.create_run(db, "r2", 2, {})
            runs = storage.list_runs(db)
            assert [r["run_id"] for r in runs[:2]] == ["r2", "r1"]


class TestRepoOps:
    def test_upsert_then_inventory(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 10, {})
            storage.upsert_repo(db, "r1", "owner/repo", stars=500, pushed_at="2025-01-01T00:00:00Z")
            storage.update_repo_inventory(db, "r1", "owner/repo", ["docs/a.md"], 7)
            repos = storage.get_repos_by_status(db, "r1", "inventoried")
            assert len(repos) == 1
            assert repos[0]["url_count"] == 7

    def test_update_repo_status_error(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 10, {})
            storage.upsert_repo(db, "r1", "owner/repo")
            storage.update_repo_status(db, "r1", "owner/repo", "error", error="boom")
            assert storage.get_repos_by_status(db, "r1", "error")[0]["error"] == "boom"

    def test_repo_count_by_status(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 10, {})
            for i in range(3):
                storage.upsert_repo(db, "r1", f"o/r{i}")
            storage.update_repo_status(db, "r1", "o/r0", "error", error="x")
            counts = storage.get_repo_count_by_status(db, "r1")
            assert counts.get("pending") == 2
            assert counts.get("error") == 1


class TestFindings:
    def test_add_and_get(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 10, {})
            fid = storage.add_finding(
                db,
                "r1",
                "o/r",
                "docs/x.md",
                42,
                "http://dead.example/",
                "https://new.example/",
                "url_mutation",
                1,
                0.9,
                True,
                0.92,
            )
            assert fid >= 1
            found = storage.get_findings_for_repo(db, "r1", "o/r")
            assert len(found) == 1
            assert found[0]["confidence"] == 0.92

    def test_min_confidence_filter(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 10, {})
            storage.add_finding(db, "r1", "o/r", "f", 1, "d", "c", "m", 1, 0.5, True, 0.55)
            storage.add_finding(db, "r1", "o/r", "f", 2, "d", "c", "m", 1, 0.9, True, 0.91)
            high = storage.get_findings_for_repo(db, "r1", "o/r", min_confidence=0.7)
            assert len(high) == 1
            assert high[0]["confidence"] == 0.91

    def test_mark_surfaced(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 10, {})
            ids = [storage.add_finding(db, "r1", "o/r", "f", i, "d", "c", "m", 1, 0.9, True, 0.9) for i in range(3)]
            storage.mark_findings_surfaced(db, ids[:2])
            assert storage.count_findings(db, "r1", surfaced=True) == 2
            assert storage.count_findings(db, "r1", surfaced=False) == 1

    def test_get_surfaced_ranked(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 10, {})
            ids = []
            for i, conf in enumerate([0.8, 0.95, 0.75]):
                fid = storage.add_finding(db, "r1", "o/r", "f", i, "d", f"c{i}", "m", 1, 0.9, True, conf)
                ids.append(fid)
            storage.mark_findings_surfaced(db, ids)
            ranked = storage.get_surfaced_findings_ranked(db, "r1")
            assert [r["confidence"] for r in ranked] == [0.95, 0.8, 0.75]
