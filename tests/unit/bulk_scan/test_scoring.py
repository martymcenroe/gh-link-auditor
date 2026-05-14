"""Tests for bulk_scan.scoring (#218)."""

from __future__ import annotations

from gh_link_auditor.bulk_scan import storage
from gh_link_auditor.bulk_scan.scoring import (
    mark_surfaced_for_run,
    quality_sample_median,
    render_ranked_report,
    render_sample_report,
    select_top_n_per_repo,
)
from gh_link_auditor.unified_db import UnifiedDatabase


class TestSelectTopN:
    def test_top_3_per_repo(self) -> None:
        cands = [
            {"repo_full_name": "a/b", "confidence": 0.9},
            {"repo_full_name": "a/b", "confidence": 0.85},
            {"repo_full_name": "a/b", "confidence": 0.8},
            {"repo_full_name": "a/b", "confidence": 0.78},
            {"repo_full_name": "c/d", "confidence": 0.95},
        ]
        out = select_top_n_per_repo(cands, top_n=3, min_confidence=0.7)
        repo_counts: dict[str, int] = {}
        for c in out:
            repo_counts[c["repo_full_name"]] = repo_counts.get(c["repo_full_name"], 0) + 1
        assert repo_counts["a/b"] == 3
        assert repo_counts["c/d"] == 1

    def test_confidence_threshold(self) -> None:
        cands = [
            {"repo_full_name": "a/b", "confidence": 0.69},
            {"repo_full_name": "a/b", "confidence": 0.71},
        ]
        out = select_top_n_per_repo(cands, top_n=3, min_confidence=0.7)
        assert len(out) == 1
        assert out[0]["confidence"] == 0.71

    def test_empty_input(self) -> None:
        assert select_top_n_per_repo([], top_n=3) == []

    def test_descending_within_repo(self) -> None:
        cands = [
            {"repo_full_name": "a/b", "confidence": 0.7},
            {"repo_full_name": "a/b", "confidence": 0.9},
            {"repo_full_name": "a/b", "confidence": 0.8},
        ]
        out = select_top_n_per_repo(cands, top_n=3, min_confidence=0.7)
        confs = [c["confidence"] for c in out]
        assert confs == sorted(confs, reverse=True)


class TestMarkSurfacedForRun:
    def test_end_to_end(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 5, {})
            storage.upsert_repo(db, "r1", "a/b")
            for conf in [0.5, 0.71, 0.95, 0.8]:
                storage.add_finding(db, "r1", "a/b", "f", 1, "d", "c", "url_mutation", 1, 0.9, True, conf)
            count = mark_surfaced_for_run(db, "r1")
            assert count == 3  # 0.5 dropped by threshold
            surfaced = storage.get_surfaced_findings_ranked(db, "r1")
            assert [r["confidence"] for r in surfaced] == [0.95, 0.8, 0.71]


class TestQualitySampleMedian:
    def test_empty(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 5, {})
            assert quality_sample_median(db, "r1") is None

    def test_median_computed(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 5, {})
            for conf in [0.5, 0.6, 0.9, 0.95, 0.75]:
                storage.add_finding(db, "r1", "a/b", "f", 1, "d", "c", "url_mutation", 1, 0.9, True, conf)
            # median of [0.5, 0.6, 0.9, 0.95, 0.75] = 0.75
            assert quality_sample_median(db, "r1") == 0.75


class TestRenderRankedReport:
    def test_includes_run_metadata(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 5, {})
            storage.upsert_repo(db, "r1", "a/b")
            fid = storage.add_finding(
                db,
                "r1",
                "a/b",
                "docs/x.md",
                42,
                "http://dead/",
                "https://new/",
                "url_mutation",
                1,
                0.9,
                True,
                0.95,
            )
            storage.mark_findings_surfaced(db, [fid])
            report = render_ranked_report(db, "r1")
        assert "bulk scan — r1" in report
        assert "a/b" in report
        assert "http://dead/" in report
        assert "https://new/" in report
        assert "0.95" in report


class TestRenderSampleReport:
    def test_basic(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 5, {})
            storage.upsert_repo(db, "r1", "a/b")
            storage.add_finding(db, "r1", "a/b", "f", 1, "d", "c", "url_mutation", 1, 0.9, True, 0.88)
            out = render_sample_report(db, "r1", sample_size=5)
        assert "bulk scan sample — r1" in out
        assert "0.88" in out
        assert "url_mutation" in out
