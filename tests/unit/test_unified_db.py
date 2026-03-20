"""Comprehensive tests for the unified database module.

Tests cover all 14 tables, migration v1→v2, external imports,
caching, pipeline runs, repos, scans, and findings.
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from gh_link_auditor.metrics.models import PROutcome, RunReport
from gh_link_auditor.models import BlacklistEntry, InteractionRecord, InteractionStatus
from gh_link_auditor.unified_db import SCHEMA_VERSION, UnifiedDatabase

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    with UnifiedDatabase(":memory:") as database:
        yield database


@pytest.fixture
def populated_db(db):
    db.record_interaction(
        repo_url="https://github.com/owner/repo1",
        broken_url="https://example.com/dead",
        status=InteractionStatus.SUBMITTED,
        pr_url="https://github.com/owner/repo1/pull/1",
        maintainer="alice",
    )
    db.record_interaction(
        repo_url="https://github.com/owner/repo2",
        broken_url="https://example.com/gone",
        status=InteractionStatus.MERGED,
        pr_url="https://github.com/owner/repo2/pull/5",
        maintainer="bob",
    )
    return db


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------


class TestSchemaCreation:
    def test_all_tables_exist(self, db):
        tables = {row[0] for row in db._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        expected = {
            "schema_version",
            "repos",
            "scans",
            "findings",
            "interactions",
            "blacklist",
            "run_reports",
            "pr_outcomes",
            "repo_trust",
            "recheck_queue",
            "submissions",
            "api_calls",
            "url_check_cache",
            "archive_cache",
            "pipeline_runs",
        }
        assert expected.issubset(tables)

    def test_schema_version_is_current(self, db):
        row = db._conn.execute("SELECT version FROM schema_version").fetchone()
        assert row["version"] == SCHEMA_VERSION

    def test_blacklist_has_source_column(self, db):
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(blacklist)").fetchall()}
        assert "source" in cols

    def test_findings_has_is_historical_file(self, db):
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(findings)").fetchall()}
        assert "is_historical_file" in cols

    def test_pr_outcomes_has_repo_id_and_is_tier2(self, db):
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(pr_outcomes)").fetchall()}
        assert "repo_id" in cols
        assert "is_tier2" in cols

    def test_repos_table_columns(self, db):
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(repos)").fetchall()}
        for col in ("full_name", "stars", "contributors", "pushed_at", "has_contributing"):
            assert col in cols

    def test_recheck_queue_columns(self, db):
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(recheck_queue)").fetchall()}
        for col in ("finding_id", "snooze_until", "reason", "created_at"):
            assert col in cols

    def test_url_check_cache_columns(self, db):
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(url_check_cache)").fetchall()}
        for col in ("url", "http_status", "is_bot_blocked", "retry_count", "expires_at"):
            assert col in cols

    def test_archive_cache_columns(self, db):
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(archive_cache)").fetchall()}
        for col in ("url", "has_snapshot", "snapshot_url", "retry_count", "expires_at"):
            assert col in cols

    def test_pipeline_runs_columns(self, db):
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(pipeline_runs)").fetchall()}
        for col in ("run_id", "target", "last_node", "state_json", "status"):
            assert col in cols


# ---------------------------------------------------------------------------
# Migration v1 → v2
# ---------------------------------------------------------------------------


class TestMigration:
    def test_migrate_v1_to_v2(self, tmp_path):
        db_file = str(tmp_path / "legacy.db")

        # Create a v1 database manually
        conn = sqlite3.connect(db_file)
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        conn.execute("""
            CREATE TABLE interactions (
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
        conn.execute("CREATE INDEX idx_interactions_repo_url ON interactions (repo_url, broken_url)")
        conn.execute("CREATE INDEX idx_interactions_maintainer ON interactions (maintainer)")
        conn.execute("""
            CREATE TABLE blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_url TEXT,
                maintainer TEXT,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                expires_at TEXT
            )
        """)
        conn.execute("CREATE INDEX idx_blacklist_repo ON blacklist (repo_url)")
        conn.execute("CREATE INDEX idx_blacklist_maintainer ON blacklist (maintainer)")

        # Insert some v1 data
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO interactions (repo_url, broken_url, status, created_at, updated_at) VALUES (?,?,?,?,?)",
            ("https://github.com/a/b", "https://dead.link", "submitted", now, now),
        )
        conn.execute(
            "INSERT INTO blacklist (repo_url, reason, created_at) VALUES (?,?,?)",
            ("https://github.com/bad/repo", "spam", now),
        )
        conn.commit()
        conn.close()

        # Open with UnifiedDatabase — should auto-migrate
        with UnifiedDatabase(db_file) as db:
            # Version should be bumped
            row = db._conn.execute("SELECT version FROM schema_version").fetchone()
            assert row["version"] == SCHEMA_VERSION

            # Old data should still be there
            assert db.has_been_submitted("https://github.com/a/b", "https://dead.link")
            assert db.is_blacklisted("https://github.com/bad/repo")

            # Blacklist should have source column
            cols = {row[1] for row in db._conn.execute("PRAGMA table_info(blacklist)").fetchall()}
            assert "source" in cols

            # New tables should exist
            tables = {
                row[0] for row in db._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            assert "repos" in tables
            assert "findings" in tables
            assert "url_check_cache" in tables

    def test_already_v2_no_migration(self, db):
        """Opening an already-v2 database doesn't fail."""
        row = db._conn.execute("SELECT version FROM schema_version").fetchone()
        assert row["version"] == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Interactions (backward compatibility with StateDatabase)
# ---------------------------------------------------------------------------


class TestInteractions:
    def test_record_and_retrieve(self, db):
        rid = db.record_interaction(
            repo_url="https://github.com/o/r",
            broken_url="https://example.com/dead",
            status=InteractionStatus.SUBMITTED,
            pr_url="https://github.com/o/r/pull/1",
            maintainer="alice",
            notes="test",
        )
        assert isinstance(rid, int)
        record = db.get_interaction("https://github.com/o/r", "https://example.com/dead")
        assert record is not None
        assert isinstance(record, InteractionRecord)
        assert record.status == InteractionStatus.SUBMITTED
        assert record.pr_url == "https://github.com/o/r/pull/1"
        assert record.maintainer == "alice"

    def test_record_minimal(self, db):
        db.record_interaction(
            repo_url="https://github.com/o/r",
            broken_url="https://example.com/dead",
            status=InteractionStatus.SUBMITTED,
        )
        record = db.get_interaction("https://github.com/o/r", "https://example.com/dead")
        assert record is not None
        assert record.pr_url is None
        assert record.maintainer is None

    def test_has_been_submitted(self, db):
        assert db.has_been_submitted("https://github.com/o/r", "https://example.com/dead") is False
        db.record_interaction(
            repo_url="https://github.com/o/r",
            broken_url="https://example.com/dead",
            status=InteractionStatus.SUBMITTED,
        )
        assert db.has_been_submitted("https://github.com/o/r", "https://example.com/dead") is True

    def test_update_status(self, db):
        rid = db.record_interaction(
            repo_url="https://github.com/o/r",
            broken_url="https://example.com/dead",
            status=InteractionStatus.SUBMITTED,
        )
        time.sleep(0.05)
        success = db.update_interaction_status(rid, InteractionStatus.MERGED)
        assert success is True
        record = db.get_interaction("https://github.com/o/r", "https://example.com/dead")
        assert record is not None
        assert record.status == InteractionStatus.MERGED

    def test_update_nonexistent(self, db):
        assert db.update_interaction_status(9999, InteractionStatus.MERGED) is False

    def test_get_interaction_returns_latest(self, db):
        db.record_interaction(
            repo_url="https://github.com/o/r",
            broken_url="https://example.com/dead",
            status=InteractionStatus.SUBMITTED,
        )
        time.sleep(0.05)
        db.record_interaction(
            repo_url="https://github.com/o/r",
            broken_url="https://example.com/dead",
            status=InteractionStatus.DENIED,
            notes="Second",
        )
        record = db.get_interaction("https://github.com/o/r", "https://example.com/dead")
        assert record is not None
        assert record.status == InteractionStatus.DENIED

    def test_get_interaction_returns_none(self, db):
        assert db.get_interaction("no", "no") is None


# ---------------------------------------------------------------------------
# Blacklist
# ---------------------------------------------------------------------------


class TestBlacklist:
    def test_add_and_check(self, db):
        eid = db.add_to_blacklist(repo_url="https://github.com/bad/r", reason="spam")
        assert isinstance(eid, int)
        assert db.is_blacklisted("https://github.com/bad/r") is True
        assert db.is_blacklisted("https://github.com/good/r") is False

    def test_add_maintainer(self, db):
        db.add_to_blacklist(maintainer="evil", reason="abusive")
        assert db.is_blacklisted("https://github.com/any/r", maintainer="evil") is True
        assert db.is_blacklisted("https://github.com/any/r", maintainer="nice") is False

    def test_requires_target(self, db):
        with pytest.raises(ValueError, match="At least one"):
            db.add_to_blacklist(reason="nope")

    def test_expiration(self, db):
        past = datetime.now(timezone.utc) - timedelta(days=1)
        db.add_to_blacklist(repo_url="https://github.com/exp/r", reason="temp", expires_at=past)
        assert db.is_blacklisted("https://github.com/exp/r") is False

    def test_not_expired(self, db):
        future = datetime.now(timezone.utc) + timedelta(days=30)
        db.add_to_blacklist(repo_url="https://github.com/act/r", reason="temp", expires_at=future)
        assert db.is_blacklisted("https://github.com/act/r") is True

    def test_remove(self, db):
        eid = db.add_to_blacklist(repo_url="https://github.com/r/r", reason="test")
        assert db.remove_from_blacklist(eid) is True
        assert db.is_blacklisted("https://github.com/r/r") is False

    def test_remove_nonexistent(self, db):
        assert db.remove_from_blacklist(9999) is False

    def test_get_blacklist(self, db):
        db.add_to_blacklist(repo_url="https://github.com/a/b", reason="ban")
        db.add_to_blacklist(maintainer="bad", reason="abuse")
        entries = db.get_blacklist()
        assert len(entries) == 2
        assert all(isinstance(e, BlacklistEntry) for e in entries)

    def test_get_blacklist_excludes_expired(self, db):
        past = datetime.now(timezone.utc) - timedelta(days=1)
        db.add_to_blacklist(repo_url="https://github.com/exp/r", expires_at=past)
        db.add_to_blacklist(repo_url="https://github.com/act/r")
        entries = db.get_blacklist()
        assert len(entries) == 1

    def test_source_field(self, db):
        db.add_to_blacklist(repo_url="https://github.com/a/b", source="behavior")
        row = db._conn.execute(
            "SELECT source FROM blacklist WHERE repo_url = ?", ("https://github.com/a/b",)
        ).fetchone()
        assert row["source"] == "behavior"

    def test_can_submit_fix_ok(self, db):
        ok, reason = db.can_submit_fix("https://github.com/o/r", "https://x.com/dead")
        assert ok is True
        assert reason == "ok"

    def test_can_submit_fix_blacklisted(self, db):
        db.add_to_blacklist(repo_url="https://github.com/o/r")
        ok, reason = db.can_submit_fix("https://github.com/o/r", "https://x.com/dead")
        assert ok is False
        assert "blacklisted" in reason

    def test_can_submit_fix_duplicate(self, db):
        db.record_interaction(
            repo_url="https://github.com/o/r",
            broken_url="https://x.com/dead",
            status=InteractionStatus.SUBMITTED,
        )
        ok, reason = db.can_submit_fix("https://github.com/o/r", "https://x.com/dead")
        assert ok is False
        assert "already" in reason


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_stats(self, populated_db):
        stats = populated_db.get_stats()
        assert stats["total_interactions"] == 2
        assert stats["by_status"]["submitted"] == 1
        assert stats["by_status"]["merged"] == 1
        assert stats["active_blacklist_entries"] == 0

    def test_stats_empty(self, db):
        stats = db.get_stats()
        assert stats["total_interactions"] == 0
        assert stats["by_status"] == {}

    def test_stats_with_blacklist(self, db):
        db.add_to_blacklist(repo_url="https://github.com/a/b")
        stats = db.get_stats()
        assert stats["active_blacklist_entries"] == 1
        assert stats["total_blacklist_entries"] == 1


# ---------------------------------------------------------------------------
# Run Reports (MetricsCollector compat)
# ---------------------------------------------------------------------------


class TestRunReports:
    def _make_report(self, batch_id="test-001", repos=10):
        return RunReport(
            batch_id=batch_id,
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            completed_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
            repos_scanned=repos,
            repos_succeeded=repos - 2,
            repos_failed=2,
            repos_skipped=0,
            total_links_found=100,
            total_broken_links=20,
            total_fixes_generated=15,
            total_prs_submitted=5,
            duration_seconds=3600.0,
            errors=[{"repo": "a/b", "error_message": "boom"}],
        )

    def test_record_and_retrieve(self, db):
        db.record_run(self._make_report())
        runs = db.get_all_runs()
        assert len(runs) == 1
        assert runs[0].batch_id == "test-001"
        assert runs[0].repos_scanned == 10
        assert runs[0].errors == [{"repo": "a/b", "error_message": "boom"}]

    def test_upsert(self, db):
        db.record_run(self._make_report(repos=5))
        db.record_run(self._make_report(repos=10))
        runs = db.get_all_runs()
        assert len(runs) == 1
        assert runs[0].repos_scanned == 10

    def test_multiple_runs(self, db):
        for i in range(3):
            db.record_run(self._make_report(batch_id=f"run-{i}", repos=10 * (i + 1)))
        runs = db.get_all_runs()
        assert len(runs) == 3


class TestPROutcomes:
    def test_record_and_retrieve(self, db):
        outcome = PROutcome(
            repo_full_name="o/r",
            pr_url="https://github.com/o/r/pull/1",
            submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            status="merged",
            merged_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            time_to_merge_hours=24.0,
        )
        db.record_pr_outcome(outcome)
        outcomes = db.get_all_pr_outcomes()
        assert len(outcomes) == 1
        assert outcomes[0].status == "merged"
        assert outcomes[0].time_to_merge_hours == 24.0

    def test_upsert_pr_outcome(self, db):
        o1 = PROutcome(
            repo_full_name="o/r",
            pr_url="https://github.com/o/r/pull/1",
            submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            status="open",
        )
        db.record_pr_outcome(o1)
        o2 = PROutcome(
            repo_full_name="o/r",
            pr_url="https://github.com/o/r/pull/1",
            submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            status="merged",
            merged_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        db.record_pr_outcome(o2)
        outcomes = db.get_all_pr_outcomes()
        assert len(outcomes) == 1
        assert outcomes[0].status == "merged"


# ---------------------------------------------------------------------------
# Submissions (StateStore compat)
# ---------------------------------------------------------------------------


class TestSubmissions:
    def test_record_and_check(self, db):
        db.record_submission(
            repo_owner="org",
            repo_name="repo",
            branch_name="fix/test",
            pr_number=42,
            pr_url="https://github.com/org/repo/pull/42",
            status="submitted",
            broken_links=[{"original_url": "https://old.com", "source_file": "README.md"}],
        )
        assert db.was_link_already_fixed("org", "repo", "https://old.com") is True
        assert db.was_link_already_fixed("org", "repo", "https://new.com") is False

    def test_different_repo(self, db):
        db.record_submission(
            repo_owner="org",
            repo_name="repo1",
            branch_name="fix/test",
            pr_number=1,
            pr_url="url",
            status="submitted",
            broken_links=[{"original_url": "https://old.com"}],
        )
        assert db.was_link_already_fixed("org", "repo2", "https://old.com") is False

    def test_daily_count(self, db):
        assert db.get_daily_submission_count() == 0
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        db.record_submission(
            repo_owner="o",
            repo_name="r",
            branch_name="b",
            pr_number=1,
            pr_url="u",
            status="s",
            broken_links=[],
            submitted_at=f"{today}T12:00:00+00:00",
        )
        assert db.get_daily_submission_count() == 1

    def test_daily_count_ignores_yesterday(self, db):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        db.record_submission(
            repo_owner="o",
            repo_name="r",
            branch_name="b",
            pr_number=1,
            pr_url="u",
            status="s",
            broken_links=[],
            submitted_at=f"{yesterday}T12:00:00+00:00",
        )
        assert db.get_daily_submission_count() == 0


# ---------------------------------------------------------------------------
# API Calls
# ---------------------------------------------------------------------------


class TestApiCalls:
    def test_empty(self, db):
        assert db.get_hourly_api_count() == 0

    def test_increment(self, db):
        db.increment_api_count()
        db.increment_api_count()
        assert db.get_hourly_api_count() == 2


# ---------------------------------------------------------------------------
# URL Check Cache
# ---------------------------------------------------------------------------


class TestUrlCheckCache:
    def test_cache_and_retrieve(self, db):
        db.cache_url_check("https://example.com", 200, final_url="https://example.com/")
        result = db.get_cached_url_check("https://example.com")
        assert result is not None
        assert result["http_status"] == 200
        assert result["final_url"] == "https://example.com/"
        assert result["is_bot_blocked"] is False

    def test_cache_miss(self, db):
        assert db.get_cached_url_check("https://nope.com") is None

    def test_cache_expired(self, db):
        db.cache_url_check("https://example.com", 200, ttl_hours=0)
        # With ttl_hours=0, expiry is now — should be expired
        # Actually ttl_hours=0 means timedelta(hours=0) so expires_at == now
        # The check is expires_at > now, so it would be expired
        # But timing might be tight, so let's use a negative approach
        # Insert with past expires_at directly
        db._conn.execute(
            "UPDATE url_check_cache SET expires_at = ? WHERE url = ?",
            ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "https://example.com"),
        )
        db._conn.commit()
        assert db.get_cached_url_check("https://example.com") is None

    def test_bot_blocked_flag(self, db):
        db.cache_url_check("https://example.com", 403, is_bot_blocked=True, retry_count=2)
        result = db.get_cached_url_check("https://example.com")
        assert result is not None
        assert result["is_bot_blocked"] is True
        assert result["retry_count"] == 2


# ---------------------------------------------------------------------------
# Archive Cache
# ---------------------------------------------------------------------------


class TestArchiveCache:
    def test_cache_and_retrieve(self, db):
        db.cache_archive_result(
            "https://dead.site/page",
            has_snapshot=True,
            snapshot_url="https://web.archive.org/web/2024/https://dead.site/page",
            snapshot_timestamp="20240101",
            title="Dead Page",
        )
        result = db.get_cached_archive("https://dead.site/page")
        assert result is not None
        assert result["has_snapshot"] is True
        assert result["title"] == "Dead Page"

    def test_cache_miss(self, db):
        assert db.get_cached_archive("https://nope.com") is None

    def test_no_snapshot(self, db):
        db.cache_archive_result("https://never.existed", has_snapshot=False)
        result = db.get_cached_archive("https://never.existed")
        assert result is not None
        assert result["has_snapshot"] is False

    def test_cache_expired(self, db):
        db.cache_archive_result("https://dead.site", has_snapshot=True)
        db._conn.execute(
            "UPDATE archive_cache SET expires_at = ? WHERE url = ?",
            ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "https://dead.site"),
        )
        db._conn.commit()
        assert db.get_cached_archive("https://dead.site") is None


# ---------------------------------------------------------------------------
# Pipeline Runs
# ---------------------------------------------------------------------------


class TestPipelineRuns:
    def test_save_and_load(self, db):
        state = {"target": "owner/repo", "dead_links": []}
        db.save_pipeline_run("run-1", "owner/repo", "n1_scan", json.dumps(state))
        result = db.load_pipeline_run("run-1")
        assert result is not None
        assert result["target"] == "owner/repo"
        assert result["last_node"] == "n1_scan"
        assert json.loads(result["state_json"]) == state

    def test_load_nonexistent(self, db):
        assert db.load_pipeline_run("nope") is None

    def test_update_pipeline_run(self, db):
        db.save_pipeline_run("run-1", "o/r", "n0", "{}")
        db.save_pipeline_run("run-1", "o/r", "n2", '{"updated": true}')
        result = db.load_pipeline_run("run-1")
        assert result is not None
        assert result["last_node"] == "n2"
        assert json.loads(result["state_json"]) == {"updated": True}

    def test_status_field(self, db):
        db.save_pipeline_run("run-1", "o/r", "n6", "{}", status="completed")
        result = db.load_pipeline_run("run-1")
        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# Repos
# ---------------------------------------------------------------------------


class TestRepos:
    def test_upsert_new(self, db):
        repo_id = db.upsert_repo("owner/repo", stars=100, contributors=5)
        assert isinstance(repo_id, int)
        repo = db.get_repo("owner/repo")
        assert repo is not None
        assert repo["stars"] == 100
        assert repo["contributors"] == 5

    def test_upsert_update(self, db):
        id1 = db.upsert_repo("owner/repo", stars=100)
        id2 = db.upsert_repo("owner/repo", stars=200)
        assert id1 == id2
        repo = db.get_repo("owner/repo")
        assert repo["stars"] == 200

    def test_get_nonexistent(self, db):
        assert db.get_repo("no/repo") is None

    def test_partial_update(self, db):
        db.upsert_repo("owner/repo", stars=100, contributors=5)
        db.upsert_repo("owner/repo", stars=200)
        repo = db.get_repo("owner/repo")
        assert repo["stars"] == 200
        assert repo["contributors"] == 5


# ---------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------


class TestScans:
    def test_record_and_complete(self, db):
        repo_id = db.upsert_repo("owner/repo")
        scan_id = db.record_scan(repo_id, "run-123")
        assert isinstance(scan_id, int)
        db.complete_scan(scan_id, dead_links_found=5, fixes_generated=3, decision="submit")
        row = db._conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
        assert row["dead_links_found"] == 5
        assert row["decision"] == "submit"
        assert row["completed_at"] is not None


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


class TestFindings:
    def test_record_finding(self, db):
        repo_id = db.upsert_repo("owner/repo")
        scan_id = db.record_scan(repo_id, "run-1")
        fid = db.record_finding(scan_id, "https://dead.link", "README.md", line_number=42, http_status=404)
        assert isinstance(fid, int)

    def test_update_finding_status(self, db):
        repo_id = db.upsert_repo("owner/repo")
        scan_id = db.record_scan(repo_id, "run-1")
        fid = db.record_finding(scan_id, "https://dead.link", "README.md")
        db.update_finding_status(fid, "approved", replacement_url="https://new.link", confidence=0.95)
        row = db._conn.execute("SELECT * FROM findings WHERE id = ?", (fid,)).fetchone()
        assert row["status"] == "approved"
        assert row["replacement_url"] == "https://new.link"
        assert row["confidence"] == 0.95

    def test_historical_file_flag(self, db):
        repo_id = db.upsert_repo("owner/repo")
        scan_id = db.record_scan(repo_id, "run-1")
        fid = db.record_finding(scan_id, "https://dead.link", "CHANGELOG.md", is_historical_file=True)
        row = db._conn.execute("SELECT is_historical_file FROM findings WHERE id = ?", (fid,)).fetchone()
        assert row["is_historical_file"] == 1


# ---------------------------------------------------------------------------
# External imports
# ---------------------------------------------------------------------------


class TestImportMetricsDb:
    def test_import_from_metrics_db(self, tmp_path, db):
        metrics_file = tmp_path / "metrics.db"
        mconn = sqlite3.connect(str(metrics_file))
        mconn.execute("""
            CREATE TABLE run_reports (
                batch_id TEXT PRIMARY KEY, started_at TEXT, completed_at TEXT,
                repos_scanned INTEGER, repos_succeeded INTEGER, repos_failed INTEGER,
                repos_skipped INTEGER, total_links_found INTEGER, total_broken_links INTEGER,
                total_fixes_generated INTEGER, total_prs_submitted INTEGER,
                duration_seconds REAL, errors_json TEXT
            )
        """)
        mconn.execute("""
            CREATE TABLE pr_outcomes (
                pr_url TEXT PRIMARY KEY, repo_full_name TEXT, submitted_at TEXT,
                status TEXT, merged_at TEXT, closed_at TEXT,
                rejection_reason TEXT, time_to_merge_hours REAL
            )
        """)
        mconn.execute(
            "INSERT INTO run_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "batch-1",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T01:00:00+00:00",
                10,
                8,
                2,
                0,
                50,
                10,
                5,
                3,
                3600.0,
                "[]",
            ),
        )
        mconn.execute(
            "INSERT INTO pr_outcomes VALUES (?,?,?,?,?,?,?,?)",
            (
                "https://github.com/o/r/pull/1",
                "o/r",
                "2026-01-01T00:00:00+00:00",
                "merged",
                "2026-01-02T00:00:00+00:00",
                None,
                None,
                24.0,
            ),
        )
        mconn.commit()
        mconn.close()

        imported = db.import_from_metrics_db(metrics_file)
        assert imported == 2
        assert len(db.get_all_runs()) == 1
        assert len(db.get_all_pr_outcomes()) == 1

    def test_import_nonexistent_file(self, db):
        assert db.import_from_metrics_db("/nonexistent/metrics.db") == 0


class TestImportTinyDb:
    def test_import_from_tinydb(self, tmp_path, db):
        tinydb_file = tmp_path / "state.json"
        data = {
            "submissions": {
                "1": {
                    "repository": {"owner": "org", "repo": "repo"},
                    "branch_name": "fix/test",
                    "pr_number": 1,
                    "pr_url": "https://github.com/org/repo/pull/1",
                    "status": "submitted",
                    "broken_links_fixed": [{"original_url": "https://old.com"}],
                    "submitted_at": "2026-01-01T00:00:00+00:00",
                }
            },
            "api_calls": {
                "1": {"timestamp": "2026-01-01T00:00:00+00:00"},
                "2": {"timestamp": "2026-01-01T01:00:00+00:00"},
            },
        }
        tinydb_file.write_text(json.dumps(data))
        imported = db.import_from_tinydb(tinydb_file)
        assert imported == 3
        assert db.was_link_already_fixed("org", "repo", "https://old.com") is True

    def test_import_nonexistent_file(self, db):
        assert db.import_from_tinydb("/nonexistent/state.json") == 0


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_data_survives_close_reopen(self, tmp_path):
        db_file = str(tmp_path / "test.db")
        with UnifiedDatabase(db_file) as db:
            db.record_interaction(
                repo_url="https://github.com/o/r",
                broken_url="https://example.com/dead",
                status=InteractionStatus.SUBMITTED,
            )
            db.add_to_blacklist(maintainer="blocked")
            db.record_run(
                RunReport(
                    batch_id="persist-test",
                    started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    completed_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
                    repos_scanned=5,
                    repos_succeeded=5,
                    repos_failed=0,
                    repos_skipped=0,
                    total_links_found=10,
                    total_broken_links=2,
                    total_fixes_generated=1,
                    total_prs_submitted=1,
                    duration_seconds=100.0,
                )
            )

        with UnifiedDatabase(db_file) as db:
            assert db.has_been_submitted("https://github.com/o/r", "https://example.com/dead")
            assert db.is_blacklisted("https://github.com/any/r", maintainer="blocked")
            assert len(db.get_all_runs()) == 1


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_enter_exit(self):
        with UnifiedDatabase(":memory:") as db:
            db.record_interaction(
                repo_url="https://github.com/o/r",
                broken_url="https://example.com/dead",
                status=InteractionStatus.SUBMITTED,
            )
        with pytest.raises(Exception):
            db._conn.execute("SELECT 1")

    def test_creates_parent_dirs(self, tmp_path):
        db_file = tmp_path / "nested" / "dir" / "test.db"
        with UnifiedDatabase(db_file) as db:
            row = db._conn.execute("SELECT version FROM schema_version").fetchone()
            assert row["version"] == SCHEMA_VERSION
