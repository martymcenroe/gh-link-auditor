"""Tests for src/gh_link_auditor/preflight/gates.py (#289, #291-#293, #295-#297)."""

from __future__ import annotations

from typing import Any

import pytest

from gh_link_auditor.preflight.gates import (
    DEFAULT_STARS_FLOOR,
    HARD_GATES,
    gate_candidate_url_alive,
    gate_dead_url_still_dead,
    gate_dead_url_still_present,
    gate_no_duplicate_pr,
    gate_no_markdown_corruption,
    gate_repo_active,
    gate_stars_floor,
)
from gh_link_auditor.repo_quality import RepoQuality
from gh_link_auditor.unified_db import UnifiedDatabase


@pytest.fixture
def db():
    with UnifiedDatabase(":memory:") as database:
        yield database


def _candidate(**overrides) -> dict[str, Any]:
    base = {
        "dead_url": "https://dead.example/x",
        "candidate_url": "https://alive.example/x",
        "source_file": "README.md",
        "line_number": 47,
        "method": "github_api_redirect",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# #289: repo archived/disabled
# ---------------------------------------------------------------------------


class TestGateRepoActive:
    def test_passes_when_repo_active(self, db, monkeypatch):
        monkeypatch.setattr(
            "gh_link_auditor.preflight.gates.fetch_repo_metadata",
            lambda owner, name: RepoQuality(stars=100, pushed_at="2026-05-01T00:00:00Z"),
        )
        result = gate_repo_active("owner/r", _candidate(), db)
        assert result.passed is True
        assert result.evidence["archived"] is False
        assert result.evidence["disabled"] is False

    def test_fails_when_archived(self, db, monkeypatch):
        monkeypatch.setattr(
            "gh_link_auditor.preflight.gates.fetch_repo_metadata",
            lambda owner, name: RepoQuality(stars=100, archived=True),
        )
        result = gate_repo_active("owner/r", _candidate(), db)
        assert result.passed is False
        assert "archived" in result.reason

    def test_fails_when_disabled(self, db, monkeypatch):
        monkeypatch.setattr(
            "gh_link_auditor.preflight.gates.fetch_repo_metadata",
            lambda owner, name: RepoQuality(stars=100, disabled=True),
        )
        result = gate_repo_active("owner/r", _candidate(), db)
        assert result.passed is False
        assert "disabled" in result.reason

    def test_uses_cache_on_second_call(self, db, monkeypatch):
        calls = []

        def fetch(owner, name):
            calls.append((owner, name))
            return RepoQuality(stars=200)

        monkeypatch.setattr("gh_link_auditor.preflight.gates.fetch_repo_metadata", fetch)
        gate_repo_active("owner/r", _candidate(), db)
        gate_repo_active("owner/r", _candidate(), db)
        assert len(calls) == 1  # second call hit cache


# ---------------------------------------------------------------------------
# #291: dead URL no longer present in upstream file
# ---------------------------------------------------------------------------


class TestGateDeadUrlStillPresent:
    def test_passes_when_url_present(self, db):
        def fake_fetch(repo, path):
            return "before\nThe dead link is https://dead.example/x in the docs.\nafter"

        result = gate_dead_url_still_present(
            "owner/r",
            _candidate(),
            db,
            content_fetch=fake_fetch,
        )
        assert result.passed is True

    def test_fails_when_url_absent(self, db):
        result = gate_dead_url_still_present(
            "owner/r",
            _candidate(),
            db,
            content_fetch=lambda repo, path: "rewritten upstream; no broken link here",
        )
        assert result.passed is False
        assert "no longer appears" in result.reason

    def test_fails_when_fetch_returns_none(self, db):
        result = gate_dead_url_still_present(
            "owner/r",
            _candidate(),
            db,
            content_fetch=lambda repo, path: None,
        )
        assert result.passed is False
        assert "could not be fetched" in result.reason

    def test_fails_when_candidate_missing_fields(self, db):
        result = gate_dead_url_still_present(
            "owner/r",
            {"dead_url": "", "candidate_url": ""},
            db,
            content_fetch=lambda repo, path: "anything",
        )
        assert result.passed is False


# ---------------------------------------------------------------------------
# #292: dead URL is now alive
# ---------------------------------------------------------------------------


class TestGateDeadUrlStillDead:
    def test_passes_when_dead_url_returns_4xx(self, db):
        result = gate_dead_url_still_dead(
            "owner/r",
            _candidate(),
            db,
            http_check=lambda url: {"status_code": 404, "status": "error"},
        )
        assert result.passed is True

    def test_passes_when_dead_url_unreachable(self, db):
        result = gate_dead_url_still_dead(
            "owner/r",
            _candidate(),
            db,
            http_check=lambda url: {"status_code": None, "status": "failed"},
        )
        assert result.passed is True

    def test_fails_when_dead_url_returns_2xx(self, db):
        result = gate_dead_url_still_dead(
            "owner/r",
            _candidate(),
            db,
            http_check=lambda url: {"status_code": 200, "status": "ok"},
        )
        assert result.passed is False
        assert "resurrected" in result.reason


# ---------------------------------------------------------------------------
# #293: candidate URL not 2xx
# ---------------------------------------------------------------------------


class TestGateCandidateUrlAlive:
    def test_passes_when_candidate_returns_200(self, db):
        result = gate_candidate_url_alive(
            "owner/r",
            _candidate(),
            db,
            http_check=lambda url: {"status_code": 200, "status": "ok", "final_url": url},
        )
        assert result.passed is True

    def test_passes_when_redirect_to_2xx(self, db):
        result = gate_candidate_url_alive(
            "owner/r",
            _candidate(),
            db,
            http_check=lambda url: {"status_code": 301, "status": "ok", "final_url": "https://alive.example/canonical"},
        )
        assert result.passed is True
        assert result.evidence["final_url"] == "https://alive.example/canonical"

    def test_fails_when_404(self, db):
        result = gate_candidate_url_alive(
            "owner/r",
            _candidate(),
            db,
            http_check=lambda url: {"status_code": 404, "status": "error"},
        )
        assert result.passed is False


# ---------------------------------------------------------------------------
# #295: duplicate PR already open
# ---------------------------------------------------------------------------


class TestGateNoDuplicatePr:
    def test_passes_when_no_open_prs(self, db):
        result = gate_no_duplicate_pr(
            "owner/r",
            _candidate(),
            db,
            gh_get=lambda path: [],
        )
        assert result.passed is True
        assert result.evidence["open_pr_count"] == 0

    def test_fails_when_open_pr_mentions_dead_url(self, db):
        result = gate_no_duplicate_pr(
            "owner/r",
            _candidate(),
            db,
            gh_get=lambda path: [
                {
                    "number": 42,
                    "html_url": "https://github.com/owner/r/pull/42",
                    "title": "Fix broken link",
                    "body": "Replaces https://dead.example/x",
                }
            ],
        )
        assert result.passed is False
        assert result.evidence["pr_number"] == 42

    def test_fails_when_open_pr_mentions_candidate_url(self, db):
        result = gate_no_duplicate_pr(
            "owner/r",
            _candidate(),
            db,
            gh_get=lambda path: [
                {
                    "number": 99,
                    "html_url": "https://github.com/owner/r/pull/99",
                    "title": "Add new docs",
                    "body": "uses https://alive.example/x for things",
                }
            ],
        )
        assert result.passed is False

    def test_passes_when_gh_returns_non_list(self, db):
        # Defensive: gh api errors return None / non-list -> assume no duplicate
        result = gate_no_duplicate_pr(
            "owner/r",
            _candidate(),
            db,
            gh_get=lambda path: None,
        )
        assert result.passed is True


# ---------------------------------------------------------------------------
# #296: markdown corruption (reuse _is_safely_replaceable)
# ---------------------------------------------------------------------------


class TestGateNoMarkdownCorruption:
    def test_passes_on_safe_replacement(self, db):
        # candidate is a different URL entirely, no prefix relationship
        result = gate_no_markdown_corruption(
            "owner/r",
            _candidate(dead_url="https://old.example/", candidate_url="https://new.example/"),
            db,
        )
        assert result.passed is True

    def test_fails_when_dead_has_unbalanced_paren(self, db):
        # dead URL captured extra ) from surrounding markdown
        result = gate_no_markdown_corruption(
            "owner/r",
            _candidate(
                dead_url="https://en.wikipedia.org/wiki/Foo)", candidate_url="https://en.wikipedia.org/wiki/Foo"
            ),
            db,
        )
        assert result.passed is False
        assert "unbalanced_paren" in result.evidence["reason"]


# ---------------------------------------------------------------------------
# #297: stars floor
# ---------------------------------------------------------------------------


class TestGateStarsFloor:
    def test_passes_when_stars_at_or_above_floor(self, db, monkeypatch):
        monkeypatch.setattr(
            "gh_link_auditor.preflight.gates.fetch_repo_metadata",
            lambda owner, name: RepoQuality(stars=20),
        )
        result = gate_stars_floor("owner/r", _candidate(), db)
        assert result.passed is True

    def test_fails_when_stars_below_floor(self, db, monkeypatch):
        monkeypatch.setattr(
            "gh_link_auditor.preflight.gates.fetch_repo_metadata",
            lambda owner, name: RepoQuality(stars=3),
        )
        result = gate_stars_floor("owner/r", _candidate(), db)
        assert result.passed is False
        assert result.evidence["stars"] == 3
        assert result.evidence["floor"] == DEFAULT_STARS_FLOOR

    def test_custom_floor(self, db, monkeypatch):
        monkeypatch.setattr(
            "gh_link_auditor.preflight.gates.fetch_repo_metadata",
            lambda owner, name: RepoQuality(stars=15),
        )
        result = gate_stars_floor("owner/r", _candidate(), db, floor=10)
        assert result.passed is True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestHardGatesRegistry:
    def test_registry_contains_all_seven_pr_delta_gates(self):
        assert len(HARD_GATES) == 7
        gate_names = {fn.__name__ for fn in HARD_GATES}
        assert gate_names == {
            "gate_repo_active",
            "gate_dead_url_still_present",
            "gate_dead_url_still_dead",
            "gate_candidate_url_alive",
            "gate_no_duplicate_pr",
            "gate_no_markdown_corruption",
            "gate_stars_floor",
        }
