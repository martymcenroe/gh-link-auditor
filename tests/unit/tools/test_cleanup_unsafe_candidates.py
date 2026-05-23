"""Tests for tools/cleanup_unsafe_candidates.py (#275)."""

from __future__ import annotations

import argparse

import pytest

from gh_link_auditor.unified_db import UnifiedDatabase
from tools import cleanup_unsafe_candidates as mod


def _make_row(**overrides) -> dict:
    base = {
        "id": 1,
        "run_id": "test-run",
        "repo_full_name": "owner/repo",
        "source_file": "README.md",
        "line_number": 5,
        "dead_url": "https://old.example.com",
        "candidate_url": "https://new.example.com",
        "method": "github_api_redirect",
        "tier": 1,
        "similarity_score": 1.0,
        "verified_live": 1,
        "confidence": 1.0,
        "surfaced": 0,
        "created_at": "2026-05-23T15:00:00+00:00",
        "investigation_state": "derived_candidate",
    }
    base.update(overrides)
    return base


def _insert(udb: UnifiedDatabase, **overrides) -> int:
    row = _make_row(**overrides)
    cur = udb._conn.execute(
        """INSERT INTO bulk_scan_findings
           (run_id, repo_full_name, source_file, line_number, dead_url, candidate_url,
            method, tier, similarity_score, verified_live, confidence, surfaced,
            created_at, investigation_state)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            row["run_id"],
            row["repo_full_name"],
            row["source_file"],
            row["line_number"],
            row["dead_url"],
            row["candidate_url"],
            row["method"],
            row["tier"],
            row["similarity_score"],
            row["verified_live"],
            row["confidence"],
            row["surfaced"],
            row["created_at"],
            row["investigation_state"],
        ),
    )
    udb._conn.commit()
    return cur.lastrowid


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def _make_args(**overrides) -> argparse.Namespace:
    defaults = {"db": "/tmp/x", "apply": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestLoadUnsafeRows:
    def test_finds_unbalanced_paren(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert(
                udb,
                dead_url="https://en.wikipedia.org/wiki/Okapi_BM25)'s",
                candidate_url="https://en.wikipedia.org/wiki/Okapi_BM25",
            )
            unsafe = mod._load_unsafe_rows(udb)
        assert len(unsafe) == 1
        assert unsafe[0]["reason"] == "unbalanced_paren"

    def test_finds_markdown_suffix(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert(
                udb,
                dead_url='https://example.com/page"',
                candidate_url="https://example.com/page",
            )
            unsafe = mod._load_unsafe_rows(udb)
        assert len(unsafe) == 1
        assert unsafe[0]["reason"] == "dead_url_suffix_has_markdown_chars"

    def test_ignores_safe_candidates(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert(
                udb,
                dead_url="https://docs.example.com/old/index.html",
                candidate_url="https://docs.example.com/new/index.html",
            )
            _insert(
                udb,
                dead_url="https://sumo.dlr.de/docs/Installing/index.htm",
                candidate_url="https://sumo.dlr.de/docs/Installing/",
            )
            unsafe = mod._load_unsafe_rows(udb)
        assert unsafe == []

    def test_skips_already_surfaced(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert(
                udb,
                surfaced=1,
                dead_url="https://en.wikipedia.org/wiki/Foo)'s",
                candidate_url="https://en.wikipedia.org/wiki/Foo",
            )
            unsafe = mod._load_unsafe_rows(udb)
        assert unsafe == []

    def test_skips_non_derived_state(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert(
                udb,
                investigation_state="pending",
                dead_url="https://en.wikipedia.org/wiki/Foo)'s",
                candidate_url="https://en.wikipedia.org/wiki/Foo",
            )
            unsafe = mod._load_unsafe_rows(udb)
        assert unsafe == []


class TestMarkDropped:
    def test_marks_rows(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            id1 = _insert(udb)
            id2 = _insert(udb)
            mod._mark_dropped(udb, [id1, id2])
            r1 = udb._conn.execute(
                "SELECT investigation_state FROM bulk_scan_findings WHERE id = ?",
                (id1,),
            ).fetchone()
            r2 = udb._conn.execute(
                "SELECT investigation_state FROM bulk_scan_findings WHERE id = ?",
                (id2,),
            ).fetchone()
        assert r1["investigation_state"] == "dropped_unsafe_url"
        assert r2["investigation_state"] == "dropped_unsafe_url"

    def test_empty_noop(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            mod._mark_dropped(udb, [])


class TestCleanup:
    def test_dry_run_does_not_mutate(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert(
                udb,
                dead_url="https://en.wikipedia.org/wiki/Foo)'s",
                candidate_url="https://en.wikipedia.org/wiki/Foo",
            )
        rc = mod.cleanup(_make_args(db=db_path, apply=False))
        assert rc == 0
        with UnifiedDatabase(db_path) as udb:
            row = udb._conn.execute("SELECT investigation_state FROM bulk_scan_findings").fetchone()
            assert row["investigation_state"] == "derived_candidate"

    def test_apply_mutates(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert(
                udb,
                dead_url="https://en.wikipedia.org/wiki/Foo)'s",
                candidate_url="https://en.wikipedia.org/wiki/Foo",
            )
            _insert(
                udb,
                dead_url="https://safe.example.com/a",
                candidate_url="https://safe.example.com/b",
            )
        rc = mod.cleanup(_make_args(db=db_path, apply=True))
        assert rc == 0
        with UnifiedDatabase(db_path) as udb:
            states = [
                r["investigation_state"]
                for r in udb._conn.execute("SELECT investigation_state FROM bulk_scan_findings ORDER BY id").fetchall()
            ]
        assert states == ["dropped_unsafe_url", "derived_candidate"]

    def test_idempotent(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert(
                udb,
                dead_url="https://en.wikipedia.org/wiki/Foo)'s",
                candidate_url="https://en.wikipedia.org/wiki/Foo",
            )
        mod.cleanup(_make_args(db=db_path, apply=True))
        # Second run finds nothing
        rc = mod.cleanup(_make_args(db=db_path, apply=True))
        assert rc == 0

    def test_no_unsafe_rows_clean_exit(self, db_path):
        with UnifiedDatabase(db_path):
            pass
        rc = mod.cleanup(_make_args(db=db_path, apply=True))
        assert rc == 0


class TestBuildParser:
    def test_defaults(self):
        args = mod._build_parser().parse_args([])
        assert args.apply is False

    def test_apply_flag(self):
        args = mod._build_parser().parse_args(["--apply"])
        assert args.apply is True


class TestMain:
    def test_main_dry_run_empty_db(self, db_path):
        rc = mod.main(["--db", db_path])
        assert rc == 0
