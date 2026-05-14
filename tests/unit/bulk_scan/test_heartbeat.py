"""Tests for bulk_scan.heartbeat (#218)."""

from __future__ import annotations

from pathlib import Path

from gh_link_auditor.bulk_scan import storage
from gh_link_auditor.bulk_scan.heartbeat import write_heartbeat
from gh_link_auditor.unified_db import UnifiedDatabase


class TestWriteHeartbeat:
    def test_writes_basic_fields(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 7, {})
            storage.upsert_repo(db, "r1", "a/b")
            storage.upsert_repo(db, "r1", "c/d")
            out_path = tmp_path / "heartbeat.txt"
            write_heartbeat(db, "r1", out_path)
            content = Path(out_path).read_text(encoding="utf-8")
        assert "run_id: r1" in content
        assert "status: selecting" in content
        assert "target_repo_count: 7" in content
        assert "pending" in content  # repo status counts

    def test_silent_on_missing_run(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            out = tmp_path / "h.txt"
            # No run created — should not raise, should not write a confusing file
            write_heartbeat(db, "missing-run", out)
        assert not Path(out).exists()

    def test_creates_parent_dirs(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 1, {})
            out = tmp_path / "nested" / "dir" / "h.txt"
            write_heartbeat(db, "r1", out)
        assert Path(out).exists()

    def test_includes_sample_median(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 1, {})
            out = tmp_path / "h.txt"
            write_heartbeat(db, "r1", out, sample_median=0.84)
            content = Path(out).read_text(encoding="utf-8")
        assert "sample_median_confidence: 0.84" in content

    def test_includes_quality_aborted_flag(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 1, {})
            storage.update_run_status(db, "r1", "quality_aborted", quality_aborted=True)
            out = tmp_path / "h.txt"
            write_heartbeat(db, "r1", out)
            content = Path(out).read_text(encoding="utf-8")
        assert "QUALITY_ABORTED" in content
