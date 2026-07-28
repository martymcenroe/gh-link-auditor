"""Tests for the merge-graduation curation surface (#404)."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

import pytest

from gh_link_auditor.cli.curation_cmd import (
    STATUSES,
    build_curation_parser,
    cmd_curation_list,
    cmd_curation_set,
)
from gh_link_auditor.metrics.models import PROutcome
from gh_link_auditor.pr_tracker import _update_trust_on_merge
from gh_link_auditor.unified_db import UnifiedDatabase

MERGED_REPO = "acme/merged"
PENDING_REPO = "acme/pending"


def _ns(db_path: str, **kw) -> argparse.Namespace:
    base = {"db_path": db_path, "format": "text", "status": None, "all": False, "refresh": False}
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "c.db")
    with UnifiedDatabase(path) as db:
        db.update_repo_trust(
            MERGED_REPO, "tier2_eligible", first_merge_at="2026-05-28T14:01:00+00:00", total_prs=1, total_merges=1
        )
        db.update_repo_trust(PENDING_REPO, "tier1_pending", total_prs=1, total_merges=0)
    return path


class TestGraduationQuery:
    def test_only_merged_repos_graduate(self, db_path):
        with UnifiedDatabase(db_path) as db:
            names = [r["full_name"] for r in db.get_graduated_repos()]
        assert names == [MERGED_REPO]

    def test_untriaged_repo_defaults_to_unseen(self, db_path):
        with UnifiedDatabase(db_path) as db:
            row = db.get_graduated_repos()[0]
        assert row["status"] == "unseen"
        assert row["notes"] == ""

    def test_status_and_notes_persist(self, db_path):
        with UnifiedDatabase(db_path) as db:
            db.set_curation(MERGED_REPO, "evaluating", "has good-first-issues")
        with UnifiedDatabase(db_path) as db:
            row = db.get_graduated_repos()[0]
        assert row["status"] == "evaluating"
        assert row["notes"] == "has good-first-issues"

    def test_setting_status_without_notes_keeps_existing_notes(self, db_path):
        with UnifiedDatabase(db_path) as db:
            db.set_curation(MERGED_REPO, "evaluating", "keep me")
            db.set_curation(MERGED_REPO, "actively-contributing")
            row = db.get_graduated_repos()[0]
        assert row["status"] == "actively-contributing"
        assert row["notes"] == "keep me"

    def test_get_curation_none_before_triage(self, db_path):
        with UnifiedDatabase(db_path) as db:
            assert db.get_curation(MERGED_REPO) is None


class TestEndToEndGraduation:
    """Submission → merge → appears on the surface (issue acceptance)."""

    def test_submitted_then_merged_repo_graduates(self, tmp_path):
        path = str(tmp_path / "e2e.db")
        submitted = datetime.now(timezone.utc) - timedelta(days=2)
        merged_at = datetime.now(timezone.utc)
        with UnifiedDatabase(path) as db:
            # Submission: pipeline writes the tier1_pending trust row.
            db.update_repo_trust(MERGED_REPO, "tier1_pending", first_pr_at=submitted.isoformat(), total_prs=1)
            db.record_pr_outcome(
                PROutcome(
                    pr_url=f"https://github.com/{MERGED_REPO}/pull/1",
                    repo_full_name=MERGED_REPO,
                    submitted_at=submitted,
                    status="open",
                )
            )
            assert db.get_graduated_repos() == []  # not yet — no merge

            # Merge: pr_tracker's real promotion path fires.
            _update_trust_on_merge(db, MERGED_REPO, merged_at)

            graduated = db.get_graduated_repos()
        assert [r["full_name"] for r in graduated] == [MERGED_REPO]
        assert graduated[0]["total_merges"] == 1
        assert graduated[0]["first_merge_at"]


class TestCliList:
    def test_lists_graduated_repo(self, db_path, capsys):
        rc = cmd_curation_list(_ns(db_path))
        out = capsys.readouterr().out
        assert rc == 0
        assert MERGED_REPO in out
        assert PENDING_REPO not in out

    def test_empty_surface_explains_itself(self, tmp_path, capsys):
        path = str(tmp_path / "empty.db")
        with UnifiedDatabase(path):
            pass
        rc = cmd_curation_list(_ns(path))
        out = capsys.readouterr().out
        assert rc == 0
        assert "No merge-graduated repos yet" in out
        assert "metrics refresh" in out

    def test_passed_on_hidden_by_default_shown_with_all(self, db_path, capsys):
        with UnifiedDatabase(db_path) as db:
            db.set_curation(MERGED_REPO, "passed-on")
        cmd_curation_list(_ns(db_path))
        assert MERGED_REPO not in capsys.readouterr().out
        cmd_curation_list(_ns(db_path, all=True))
        assert MERGED_REPO in capsys.readouterr().out

    def test_status_filter(self, db_path, capsys):
        with UnifiedDatabase(db_path) as db:
            db.set_curation(MERGED_REPO, "evaluating")
        cmd_curation_list(_ns(db_path, status="evaluating"))
        assert MERGED_REPO in capsys.readouterr().out
        cmd_curation_list(_ns(db_path, status="unseen"))
        assert MERGED_REPO not in capsys.readouterr().out

    def test_json_format(self, db_path, capsys):
        rc = cmd_curation_list(_ns(db_path, format="json"))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data[0]["full_name"] == MERGED_REPO
        assert data[0]["status"] == "unseen"


class TestRefreshSignals:
    def test_refresh_stores_signals(self, db_path, capsys, monkeypatch):
        from gh_link_auditor.repo_quality import RepoQuality

        monkeypatch.setattr(
            "gh_link_auditor.repo_quality.fetch_repo_metadata",
            lambda o, r: RepoQuality(stars=1234, contributors=7, pushed_at="2026-07-20T00:00:00Z"),
        )
        cmd_curation_list(_ns(db_path, refresh=True))
        out = capsys.readouterr().out
        assert "stars=1234" in out
        assert "contributors=7" in out
        with UnifiedDatabase(db_path) as db:
            assert db.get_graduated_repos()[0]["stars"] == 1234

    def test_refresh_failure_still_lists(self, db_path, capsys, monkeypatch):
        """A GitHub hiccup must not hide the surface."""

        def boom(owner, repo):
            raise RuntimeError("gh down")

        monkeypatch.setattr("gh_link_auditor.repo_quality.fetch_repo_metadata", boom)
        rc = cmd_curation_list(_ns(db_path, refresh=True))
        assert rc == 0
        assert MERGED_REPO in capsys.readouterr().out

    def test_no_network_without_refresh(self, db_path, capsys, monkeypatch):
        def boom(owner, repo):
            raise AssertionError("must not fetch without --refresh")

        monkeypatch.setattr("gh_link_auditor.repo_quality.fetch_repo_metadata", boom)
        assert cmd_curation_list(_ns(db_path)) == 0


class TestCliSet:
    def test_sets_status(self, db_path, capsys):
        rc = cmd_curation_set(_ns(db_path, repo=MERGED_REPO, status="evaluating", notes=None))
        assert rc == 0
        assert "status set to evaluating" in capsys.readouterr().out

    def test_refuses_non_graduated_repo(self, db_path, capsys):
        rc = cmd_curation_set(_ns(db_path, repo=PENDING_REPO, status="evaluating", notes=None))
        assert rc == 1
        assert "has not merged a campaign PR" in capsys.readouterr().out
        with UnifiedDatabase(db_path) as db:
            assert db.get_curation(PENDING_REPO) is None


class TestParser:
    def test_registration_and_statuses(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        build_curation_parser(sub)
        args = parser.parse_args(["curation", "list"])
        assert args.curation_command == "list"
        args = parser.parse_args(["curation", "set", MERGED_REPO, "--status", "passed-on"])
        assert args.status == "passed-on"
        assert set(STATUSES) == {"unseen", "evaluating", "actively-contributing", "passed-on"}

    def test_rejects_unknown_status(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        build_curation_parser(sub)
        with pytest.raises(SystemExit):
            parser.parse_args(["curation", "set", MERGED_REPO, "--status", "nonsense"])


class TestMigration:
    def test_v10_db_gains_curation_table(self, tmp_path):
        """An existing v10 DB migrates without losing trust rows."""
        import sqlite3

        path = str(tmp_path / "old.db")
        with UnifiedDatabase(path) as db:
            db.update_repo_trust(
                MERGED_REPO, "tier2_eligible", first_merge_at="2026-05-28T00:00:00+00:00", total_merges=1
            )
        # Simulate a pre-#404 database.
        con = sqlite3.connect(path)
        con.execute("DROP TABLE curation")
        con.execute("UPDATE schema_version SET version = 10")
        con.commit()
        con.close()

        with UnifiedDatabase(path) as db:
            assert db.get_graduated_repos()[0]["full_name"] == MERGED_REPO
            db.set_curation(MERGED_REPO, "evaluating")
            assert db.get_curation(MERGED_REPO)["status"] == "evaluating"
