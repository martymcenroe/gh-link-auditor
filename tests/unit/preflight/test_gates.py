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
        assert result.evidence["redirect_to_renamed"] is False

    def test_passes_when_dead_url_redirects_to_renamed_github_owner(self, db):
        """github.com owner rename: old-org -> new-org. PR is a real fix."""
        result = gate_dead_url_still_dead(
            "owner/r",
            _candidate(dead_url="https://github.com/deepmind/lab/blob/master/python/README.md"),
            db,
            http_check=lambda url: {
                "status_code": 200,
                "status": "ok",
                "final_url": "https://github.com/google-deepmind/lab/blob/master/python/README.md",
            },
        )
        assert result.passed is True
        assert result.evidence["redirect_to_renamed"] is True
        assert "canonical target" in result.reason

    def test_passes_when_dead_url_redirects_to_renamed_github_repo(self, db):
        """github.com repo rename: same owner, old-name -> new-name. PR is a real fix."""
        result = gate_dead_url_still_dead(
            "owner/r",
            _candidate(dead_url="https://github.com/open-mmlab/mmclassification/blob/master/configs/x.py"),
            db,
            http_check=lambda url: {
                "status_code": 200,
                "status": "ok",
                "final_url": "https://github.com/open-mmlab/mmpretrain/blob/master/configs/x.py",
            },
        )
        assert result.passed is True
        assert result.evidence["redirect_to_renamed"] is True

    def test_passes_when_dead_url_redirects_to_different_host(self, db):
        """Different host entirely: docs moved off blogspot, etc."""
        result = gate_dead_url_still_dead(
            "owner/r",
            _candidate(dead_url="https://oldproject.blogspot.com/docs"),
            db,
            http_check=lambda url: {
                "status_code": 200,
                "status": "ok",
                "final_url": "https://oldproject.com/docs",
            },
        )
        assert result.passed is True
        assert result.evidence["redirect_to_renamed"] is True

    def test_fails_when_dead_url_redirects_within_same_repo_path(self, db):
        """Same github owner/repo, different path: docs reorganization,
        NOT a rename — the URL really is live, just rearranged."""
        result = gate_dead_url_still_dead(
            "owner/r",
            _candidate(dead_url="https://github.com/owner/repo/blob/main/old/file.md"),
            db,
            http_check=lambda url: {
                "status_code": 200,
                "status": "ok",
                "final_url": "https://github.com/owner/repo/blob/main/new/file.md",
            },
        )
        assert result.passed is False
        assert result.evidence["redirect_to_renamed"] is False

    def test_fails_when_dead_url_2xx_with_no_final_url(self, db):
        """Lazy http_check that doesn't return final_url: defaults to no-rename."""
        result = gate_dead_url_still_dead(
            "owner/r",
            _candidate(),
            db,
            http_check=lambda url: {"status_code": 200, "status": "ok"},
        )
        assert result.passed is False
        assert result.evidence["redirect_to_renamed"] is False


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
    def test_registry_contains_all_ten_gates_after_pr_epsilon(self):
        assert len(HARD_GATES) == 10
        gate_names = {fn.__name__ for fn in HARD_GATES}
        assert gate_names == {
            "gate_anti_ai",
            "gate_repo_active",
            "gate_blacklist",
            "gate_dead_url_still_present",
            "gate_dead_url_still_dead",
            "gate_candidate_url_alive",
            "gate_redirect_target_related",
            "gate_no_duplicate_pr",
            "gate_no_markdown_corruption",
            "gate_stars_floor",
        }


# ---------------------------------------------------------------------------
# #288: anti-AI text scan (subagent)
# ---------------------------------------------------------------------------


from gh_link_auditor.preflight.gates import (  # noqa: E402
    gate_anti_ai,
    gate_blacklist,
    gate_redirect_target_related,
)
from gh_link_auditor.preflight.subagent import SubagentVerdict  # noqa: E402
from tests.fakes.subagent import FakeSubagent  # noqa: E402


class TestGateAntiAi:
    def test_passes_when_no_policy_files_exist(self, db):
        result = gate_anti_ai(
            "owner/r",
            _candidate(),
            db,
            subagent=FakeSubagent.configure(default=SubagentVerdict.CLEAN),
            content_fetch=lambda repo, path: None,
        )
        assert result.passed is True
        assert "no policy files" in result.reason

    def test_passes_when_subagent_clean(self, db):
        result = gate_anti_ai(
            "owner/r",
            _candidate(),
            db,
            subagent=FakeSubagent.configure(default=SubagentVerdict.CLEAN),
            content_fetch=lambda repo, path: "We welcome contributions." if path == "README.md" else None,
            prompt_path="ignored.txt",
        )
        assert result.passed is True
        assert "clean" in result.reason

    def test_fails_when_subagent_hostile(self, db):
        result = gate_anti_ai(
            "owner/r",
            _candidate(),
            db,
            subagent=FakeSubagent.configure(default=SubagentVerdict.HOSTILE),
            content_fetch=lambda repo, path: "Please do not use AI to generate PRs." if path == "README.md" else None,
            prompt_path="ignored.txt",
        )
        assert result.passed is False
        assert "hostile" in result.reason

    def test_uncertain_returns_needs_operator_review_reason(self, db):
        result = gate_anti_ai(
            "owner/r",
            _candidate(),
            db,
            subagent=FakeSubagent.configure(default=SubagentVerdict.UNCERTAIN),
            content_fetch=lambda repo, path: "Ambiguous policy text" if path == "README.md" else None,
            prompt_path="ignored.txt",
        )
        assert result.passed is False
        assert result.reason == "needs_operator_review"


# ---------------------------------------------------------------------------
# #290: blacklist
# ---------------------------------------------------------------------------


class TestGateBlacklist:
    def test_passes_when_not_blacklisted(self, db):
        result = gate_blacklist("owner/r", _candidate(), db)
        assert result.passed is True

    def test_fails_when_repo_blacklisted(self, db):
        db.add_to_blacklist(
            repo_url="https://github.com/owner/r",
            reason="test",
            source="manual",
        )
        result = gate_blacklist("owner/r", _candidate(), db)
        assert result.passed is False
        assert "blacklisted" in result.reason

    def test_fails_when_maintainer_blacklisted(self, db):
        db.add_to_blacklist(
            maintainer="owner",
            reason="hostile_repeat_offender",
            source="auto",
        )
        result = gate_blacklist("owner/r", _candidate(), db)
        assert result.passed is False

    def test_defensive_pass_when_db_missing(self):
        result = gate_blacklist("owner/r", _candidate(), db=None)
        assert result.passed is True


# ---------------------------------------------------------------------------
# #294: redirect target (subagent semantic)
# ---------------------------------------------------------------------------


class TestGateRedirectTargetRelated:
    def test_passes_when_no_redirect(self, db):
        result = gate_redirect_target_related(
            "owner/r",
            _candidate(candidate_url="https://alive.example/x"),
            db,
            subagent=FakeSubagent.configure(default=SubagentVerdict.CLEAN),
            http_check=lambda url: {"status_code": 200, "final_url": "https://alive.example/x"},
        )
        assert result.passed is True
        assert "no redirect" in result.reason

    def test_passes_when_subagent_clean(self, db):
        result = gate_redirect_target_related(
            "owner/r",
            _candidate(candidate_url="https://alive.example/x"),
            db,
            subagent=FakeSubagent.configure(default=SubagentVerdict.CLEAN),
            http_check=lambda url: {"status_code": 301, "final_url": "https://alive.example/canonical"},
            landing_fetch=lambda url: {"title": "Same Content", "h1": "X", "body_snippet": "ok"},
            prompt_path="ignored.txt",
        )
        assert result.passed is True

    def test_fails_when_subagent_unrelated(self, db):
        result = gate_redirect_target_related(
            "owner/r",
            _candidate(candidate_url="https://alive.example/x"),
            db,
            subagent=FakeSubagent.configure(default=SubagentVerdict.UNRELATED),
            http_check=lambda url: {"status_code": 301, "final_url": "https://login.example/"},
            landing_fetch=lambda url: {"title": "Sign in", "h1": "Login", "body_snippet": "Please log in"},
            prompt_path="ignored.txt",
        )
        assert result.passed is False
        assert "unrelated" in result.reason

    def test_defensive_pass_when_no_candidate_url(self, db):
        result = gate_redirect_target_related(
            "owner/r",
            {"dead_url": "x", "candidate_url": ""},
            db,
        )
        assert result.passed is True


# ---------------------------------------------------------------------------
# Dispatch integration: needs_operator_review routes to NEEDS_OPERATOR_REVIEW verdict
# ---------------------------------------------------------------------------


class TestRunPreflightNeedsReviewDispatch:
    def test_needs_operator_review_reason_routes_to_review_verdict(self):
        from gh_link_auditor.preflight.report import GateResult, PreflightVerdict
        from tools.preflight_check import run_preflight

        def fake_uncertain_gate(repo, candidate, db):
            return GateResult(
                name="fake",
                passed=False,
                reason="needs_operator_review",
                evidence={"why": "uncertain"},
            )

        report = run_preflight(
            "owner/r",
            {"dead_url": "https://a", "candidate_url": "https://b"},
            gates=[fake_uncertain_gate],
        )
        assert report.verdict == PreflightVerdict.NEEDS_OPERATOR_REVIEW
        assert report.gate_failure_name == "fake"
