"""Tests for src/gh_link_auditor/preflight/scores.py (PR-η: #298, #299, #300, #301, #303, #304)."""

from __future__ import annotations

from typing import Any

import pytest

from gh_link_auditor.preflight.scores import (
    CORRECTNESS_SCORES,
    score_c1_url_verbatim,
    score_c2_occurrence_count,
    score_c3_dead_http_status,
    score_c4_candidate_http_status,
    score_c6_replace_simulation_valid,
    score_c7_context_preserved,
)
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
# C1: URL verbatim
# ---------------------------------------------------------------------------


class TestScoreC1:
    def test_full_points_when_url_present(self, db):
        result = score_c1_url_verbatim(
            "owner/r",
            _candidate(),
            db,
            content_fetch=lambda r, p: "Some text\nhttps://dead.example/x is the dead link\nMore text",
        )
        assert result.points_awarded == 10

    def test_zero_when_url_absent(self, db):
        result = score_c1_url_verbatim(
            "owner/r",
            _candidate(),
            db,
            content_fetch=lambda r, p: "Some text without the URL",
        )
        assert result.points_awarded == 0


# ---------------------------------------------------------------------------
# C2: occurrence count
# ---------------------------------------------------------------------------


class TestScoreC2:
    def test_full_points_for_single_occurrence(self, db):
        result = score_c2_occurrence_count(
            "owner/r",
            _candidate(),
            db,
            content_fetch=lambda r, p: "appears once: https://dead.example/x end",
        )
        assert result.points_awarded == 10
        assert result.evidence["hits"] == 1

    def test_partial_for_multi_occurrence(self, db):
        result = score_c2_occurrence_count(
            "owner/r",
            _candidate(),
            db,
            content_fetch=lambda r, p: "https://dead.example/x first\nhttps://dead.example/x second",
        )
        assert result.points_awarded == 5
        assert result.evidence["hits"] == 2
        assert result.evidence["multi_occurrence"] is True

    def test_zero_when_absent(self, db):
        result = score_c2_occurrence_count(
            "owner/r",
            _candidate(),
            db,
            content_fetch=lambda r, p: "nothing here",
        )
        assert result.points_awarded == 0


# ---------------------------------------------------------------------------
# C3: dead HTTP status
# ---------------------------------------------------------------------------


class TestScoreC3:
    def test_zero_when_no_op_fix(self, db):
        # dead == candidate -> no-op fix
        result = score_c3_dead_http_status(
            "owner/r",
            _candidate(dead_url="https://x", candidate_url="https://x"),
            db,
            http_check=lambda url: {"status_code": 200},
        )
        assert result.points_awarded == 0
        assert result.evidence["reason"] == "no_op_fix"

    def test_full_points_on_4xx(self, db):
        result = score_c3_dead_http_status(
            "owner/r",
            _candidate(),
            db,
            http_check=lambda url: {"status_code": 404},
        )
        assert result.points_awarded == 10

    def test_partial_on_5xx(self, db):
        result = score_c3_dead_http_status(
            "owner/r",
            _candidate(),
            db,
            http_check=lambda url: {"status_code": 503},
        )
        assert result.points_awarded == 5

    def test_partial_on_none(self, db):
        result = score_c3_dead_http_status(
            "owner/r",
            _candidate(),
            db,
            http_check=lambda url: {"status_code": None},
        )
        assert result.points_awarded == 5


# ---------------------------------------------------------------------------
# C4: candidate HTTP status
# ---------------------------------------------------------------------------


class TestScoreC4:
    def test_full_points_on_200(self, db):
        result = score_c4_candidate_http_status(
            "owner/r",
            _candidate(),
            db,
            http_check=lambda url: {"status_code": 200, "final_url": url},
        )
        assert result.points_awarded == 10

    def test_partial_on_redirect(self, db):
        result = score_c4_candidate_http_status(
            "owner/r",
            _candidate(),
            db,
            http_check=lambda url: {"status_code": 301, "final_url": "https://alive.example/new"},
        )
        assert result.points_awarded == 8
        assert result.evidence["redirect"] is True

    def test_zero_on_404(self, db):
        result = score_c4_candidate_http_status(
            "owner/r",
            _candidate(),
            db,
            http_check=lambda url: {"status_code": 404},
        )
        assert result.points_awarded == 0


# ---------------------------------------------------------------------------
# C6: replace simulation valid
# ---------------------------------------------------------------------------


class TestScoreC6:
    def test_full_when_brackets_balanced(self, db):
        # Simple markdown link, balanced
        content = "See the [docs](https://dead.example/x) for details."
        result = score_c6_replace_simulation_valid(
            "owner/r",
            _candidate(),
            db,
            content_fetch=lambda r, p: content,
        )
        assert result.points_awarded == 10

    def test_zero_when_replacement_creates_orphan(self, db):
        # candidate_url being empty (we don't actually test this; pretend dead is the entire link)
        content = "Link: [text](https://dead.example/x)"
        result = score_c6_replace_simulation_valid(
            "owner/r",
            _candidate(candidate_url="(unbalanced"),
            db,
            content_fetch=lambda r, p: content,
        )
        assert result.points_awarded == 0


# ---------------------------------------------------------------------------
# C7: surrounding context preserved
# ---------------------------------------------------------------------------


class TestScoreC7:
    def test_full_when_only_url_changes(self, db):
        content = "before https://dead.example/x after"
        result = score_c7_context_preserved(
            "owner/r",
            _candidate(),
            db,
            content_fetch=lambda r, p: content,
        )
        assert result.points_awarded == 10
        assert result.evidence["reason"] == "only_url_changed"

    def test_full_when_multi_occurrence_changes_all(self, db):
        content = "https://dead.example/x and https://dead.example/x again"
        result = score_c7_context_preserved(
            "owner/r",
            _candidate(),
            db,
            content_fetch=lambda r, p: content,
        )
        assert result.points_awarded == 10

    def test_zero_when_dead_url_missing(self, db):
        result = score_c7_context_preserved(
            "owner/r",
            _candidate(dead_url=""),
            db,
            content_fetch=lambda r, p: "anything",
        )
        assert result.points_awarded == 0


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestCorrectnessScoresRegistry:
    def test_registry_has_six_pr_eta_scores(self):
        assert len(CORRECTNESS_SCORES) == 6
        score_names = {fn.__name__ for fn in CORRECTNESS_SCORES}
        assert score_names == {
            "score_c1_url_verbatim",
            "score_c2_occurrence_count",
            "score_c3_dead_http_status",
            "score_c4_candidate_http_status",
            "score_c6_replace_simulation_valid",
            "score_c7_context_preserved",
        }
