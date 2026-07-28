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
    def test_registry_has_twelve_scores_after_pr_theta(self):
        assert len(CORRECTNESS_SCORES) == 12
        score_names = {fn.__name__ for fn in CORRECTNESS_SCORES}
        assert score_names == {
            "score_c1_url_verbatim",
            "score_c2_occurrence_count",
            "score_c3_dead_http_status",
            "score_c4_candidate_http_status",
            "score_c5_content_equivalence",
            "score_c6_replace_simulation_valid",
            "score_c7_context_preserved",
            "score_r1_stars",
            "score_r2_recency",
            "score_r3_outsider_merge_rate",
            "score_r4_maintainer_structure",
            "score_r5_license",
        }


# ---------------------------------------------------------------------------
# C5 (#302): content equivalence (subagent)
# ---------------------------------------------------------------------------


from gh_link_auditor.preflight.scores import (  # noqa: E402
    score_c5_content_equivalence,
    score_r1_stars,
    score_r2_recency,
    score_r3_outsider_merge_rate,
    score_r4_maintainer_structure,
    score_r5_license,
)
from gh_link_auditor.preflight.subagent import SubagentVerdict  # noqa: E402
from gh_link_auditor.repo_quality import RepoQuality  # noqa: E402
from tests.fakes.subagent import FakeSubagent  # noqa: E402


class TestScoreC5:
    def test_full_15_when_subagent_clean(self, db):
        result = score_c5_content_equivalence(
            "owner/r",
            _candidate(),
            db,
            subagent=FakeSubagent.configure(default=SubagentVerdict.CLEAN),
            landing_fetch=lambda url: {"title": "OK", "h1": "X", "body_snippet": "ok"},
            prompt_path="ignored.txt",
        )
        assert result.points_awarded == 15

    def test_partial_8_when_subagent_partial(self, db):
        result = score_c5_content_equivalence(
            "owner/r",
            _candidate(),
            db,
            subagent=FakeSubagent.configure(default=SubagentVerdict.PARTIAL),
            landing_fetch=lambda url: {"title": "Related", "h1": "Y", "body_snippet": "related"},
            prompt_path="ignored.txt",
        )
        assert result.points_awarded == 8

    def test_zero_when_subagent_unrelated(self, db):
        result = score_c5_content_equivalence(
            "owner/r",
            _candidate(),
            db,
            subagent=FakeSubagent.configure(default=SubagentVerdict.UNRELATED),
            landing_fetch=lambda url: {"title": "Sign in", "h1": "Login", "body_snippet": "login"},
            prompt_path="ignored.txt",
        )
        assert result.points_awarded == 0

    def test_zero_when_no_candidate_url(self, db):
        result = score_c5_content_equivalence(
            "owner/r",
            _candidate(candidate_url=""),
            db,
        )
        assert result.points_awarded == 0

    def test_c5_passes_dead_url_to_subagent(self, db):
        """#407: the prompt's URL-pair normalization rules need the dead URL."""
        fake = FakeSubagent.configure(default=SubagentVerdict.CLEAN)
        score_c5_content_equivalence(
            "owner/r",
            _candidate(),
            db,
            subagent=fake,
            landing_fetch=lambda url: {"title": "OK", "h1": "X", "body_snippet": "ok"},
            prompt_path="ignored.txt",
        )
        assert fake.calls[0].context["dead_url"] == "https://dead.example/x"

    def test_c5_passes_candidate_page_not_landing_page(self, db):
        """#407: context keys must match the prompt's documented contract exactly.

        The exact-set assertion pins the prompt-context contract; golden-file
        tests catch prompt drift but not context drift (lesson 2026-05-27).
        """
        fake = FakeSubagent.configure(default=SubagentVerdict.CLEAN)
        landing = {"title": "OK", "h1": "X", "body_snippet": "ok"}
        score_c5_content_equivalence(
            "owner/r",
            _candidate(),
            db,
            subagent=fake,
            landing_fetch=lambda url: dict(landing),
            prompt_path="ignored.txt",
        )
        ctx = fake.calls[0].context
        assert set(ctx) == {"dead_url", "candidate_url", "link_text", "candidate_page"}
        assert ctx["candidate_page"] == landing


class TestScoreC5FastPath:
    """Fast-path equivalence checks should short-circuit to 15/15 without
    invoking the subagent (#340)."""

    def _exploding_subagent(self):
        class Boom:
            def run(self, *_a, **_kw):  # pragma: no cover - should never be called
                raise AssertionError("subagent should NOT be invoked on fast-path match")

            def is_available(self):
                return True

        return Boom()

    def test_escape_only_equivalence(self, db):
        result = score_c5_content_equivalence(
            "owner/r",
            _candidate(
                dead_url=r"https://en.wikipedia.org/wiki/Silhouette_\(clustering\)",
                candidate_url="https://en.wikipedia.org/wiki/Silhouette_(clustering)",
            ),
            db,
            subagent=self._exploding_subagent(),
        )
        assert result.points_awarded == 15
        assert result.evidence["pattern"] == "escape_only"

    def test_index_canonical_equivalence(self, db):
        result = score_c5_content_equivalence(
            "owner/r",
            _candidate(
                dead_url="https://libspatialindex.github.io/index.html",
                candidate_url="https://libspatialindex.github.io/",
            ),
            db,
            subagent=self._exploding_subagent(),
        )
        assert result.points_awarded == 15
        assert result.evidence["pattern"] == "index_canonical"

    def test_stray_trailing_backslash(self, db):
        result = score_c5_content_equivalence(
            "owner/r",
            _candidate(
                dead_url=r"https://en.wikipedia.org/wiki/List_of_tallest_buildings_in_France\\",
                candidate_url="https://en.wikipedia.org/wiki/List_of_tallest_buildings_in_France",
            ),
            db,
            subagent=self._exploding_subagent(),
        )
        assert result.points_awarded == 15
        assert result.evidence["pattern"] == "stray_trailing"

    def test_stray_trailing_hash(self, db):
        result = score_c5_content_equivalence(
            "owner/r",
            _candidate(
                dead_url="http://www.example.com/page#",
                candidate_url="http://www.example.com/page",
            ),
            db,
            subagent=self._exploding_subagent(),
        )
        assert result.points_awarded == 15
        assert result.evidence["pattern"] == "stray_trailing"

    def test_truncation_fix_closing_paren(self, db):
        result = score_c5_content_equivalence(
            "owner/r",
            _candidate(
                dead_url="https://en.wikipedia.org/wiki/Euler_equations_(fluid_dynamics",
                candidate_url="https://en.wikipedia.org/wiki/Euler_equations_(fluid_dynamics)",
            ),
            db,
            subagent=self._exploding_subagent(),
        )
        assert result.points_awarded == 15
        assert result.evidence["pattern"] == "truncation_fix"

    def test_same_final_url_via_redirect(self, db):
        def http_check(url):
            return {"final_url": "https://canonical.example/x", "status_code": 200}

        result = score_c5_content_equivalence(
            "owner/r",
            _candidate(
                dead_url="https://oldhost.example/x",
                candidate_url="https://newhost.example/x",
            ),
            db,
            subagent=self._exploding_subagent(),
            http_check=http_check,
        )
        assert result.points_awarded == 15
        assert result.evidence["pattern"] == "same_final_url"

    def test_unrelated_urls_fall_through_to_subagent(self, db):
        """Two genuinely different URLs should NOT trigger fast-path; the
        subagent (FakeSubagent here) determines the verdict."""
        result = score_c5_content_equivalence(
            "owner/r",
            _candidate(
                dead_url="https://example.com/old-broken-page",
                candidate_url="https://different.example/wholly-different",
            ),
            db,
            subagent=FakeSubagent.configure(default=SubagentVerdict.UNRELATED),
            landing_fetch=lambda url: {"title": "X", "h1": "Y", "body_snippet": "z"},
            prompt_path="ignored.txt",
        )
        # subagent UNRELATED -> 0
        assert result.points_awarded == 0


# ---------------------------------------------------------------------------
# R1 (#305): stars tiered
# ---------------------------------------------------------------------------


class TestScoreR1Stars:
    @pytest.mark.parametrize(
        "stars,expected",
        [(2000, 5), (700, 4), (200, 3), (75, 2), (25, 1), (10, 0)],
    )
    def test_tier_boundaries(self, db, monkeypatch, stars, expected):
        monkeypatch.setattr(
            "gh_link_auditor.preflight.scores.fetch_repo_metadata",
            lambda owner, name: RepoQuality(stars=stars),
        )
        result = score_r1_stars("owner/r", _candidate(), db)
        assert result.points_awarded == expected


# ---------------------------------------------------------------------------
# R2 (#306): recency tiered
# ---------------------------------------------------------------------------


class TestScoreR2Recency:
    def test_recent_pushes_score_5(self, db, monkeypatch):
        from datetime import datetime, timedelta, timezone

        now = datetime(2026, 5, 24, tzinfo=timezone.utc)
        monkeypatch.setattr(
            "gh_link_auditor.preflight.scores.fetch_repo_metadata",
            lambda owner, name: RepoQuality(pushed_at=(now - timedelta(days=3)).isoformat()),
        )
        result = score_r2_recency("owner/r", _candidate(), db, now=now)
        assert result.points_awarded == 5

    def test_one_year_old_scores_zero(self, db, monkeypatch):
        from datetime import datetime, timedelta, timezone

        now = datetime(2026, 5, 24, tzinfo=timezone.utc)
        monkeypatch.setattr(
            "gh_link_auditor.preflight.scores.fetch_repo_metadata",
            lambda owner, name: RepoQuality(pushed_at=(now - timedelta(days=400)).isoformat()),
        )
        result = score_r2_recency("owner/r", _candidate(), db, now=now)
        assert result.points_awarded == 0

    def test_missing_pushed_at_scores_zero(self, db, monkeypatch):
        monkeypatch.setattr(
            "gh_link_auditor.preflight.scores.fetch_repo_metadata",
            lambda owner, name: RepoQuality(pushed_at=""),
        )
        result = score_r2_recency("owner/r", _candidate(), db)
        assert result.points_awarded == 0


# ---------------------------------------------------------------------------
# R3 (#307): outsider PR merge rate
# ---------------------------------------------------------------------------


class TestScoreR3OutsiderMergeRate:
    def test_full_5_at_30_percent(self, db):
        pulls = [
            {"user": {"login": "alice"}, "merged_at": "2026-01-01T00:00:00Z"},
            {"user": {"login": "bob"}, "merged_at": "2026-01-02T00:00:00Z"},
            {"user": {"login": "owner"}, "merged_at": "2026-01-03T00:00:00Z"},  # excluded
        ]
        result = score_r3_outsider_merge_rate("owner/r", _candidate(), db, gh_get=lambda p: pulls)
        assert result.points_awarded == 5  # 2/2 = 100%

    def test_zero_when_no_outsider_prs(self, db):
        pulls = [{"user": {"login": "owner"}, "merged_at": "2026-01-01T00:00:00Z"}]
        result = score_r3_outsider_merge_rate("owner/r", _candidate(), db, gh_get=lambda p: pulls)
        assert result.points_awarded == 0

    def test_zero_when_no_prs(self, db):
        result = score_r3_outsider_merge_rate("owner/r", _candidate(), db, gh_get=lambda p: [])
        assert result.points_awarded == 0

    def test_uses_cache_on_second_call(self, db):
        calls = []

        def fake_gh(path):
            calls.append(path)
            return [{"user": {"login": "alice"}, "merged_at": "2026-01-01T00:00:00Z"}]

        score_r3_outsider_merge_rate("owner/r", _candidate(), db, gh_get=fake_gh)
        score_r3_outsider_merge_rate("owner/r", _candidate(), db, gh_get=fake_gh)
        # Second call should hit the cache and skip the API
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# R4 (#308): maintainer structure
# ---------------------------------------------------------------------------


class TestScoreR4MaintainerStructure:
    def test_full_for_organization_owned(self, db):
        def fake_gh(path):
            if path == "repos/owner/r":
                return {"owner": {"type": "Organization"}}
            return None

        result = score_r4_maintainer_structure("owner/r", _candidate(), db, gh_get=fake_gh)
        assert result.points_awarded == 5

    def test_full_for_multiple_contributors(self, db):
        def fake_gh(path):
            if path == "repos/owner/r":
                return {"owner": {"type": "User"}}
            if "contributors" in path:
                return [{"login": "a"}, {"login": "b"}]
            return None

        result = score_r4_maintainer_structure("owner/r", _candidate(), db, gh_get=fake_gh)
        assert result.points_awarded == 5

    def test_full_when_codeowners_exists(self, db):
        def fake_gh(path):
            if path == "repos/owner/r":
                return {"owner": {"type": "User"}}
            if "contributors" in path:
                return [{"login": "solo"}]
            if "CODEOWNERS" in path:
                return {"name": "CODEOWNERS"}
            return None

        result = score_r4_maintainer_structure("owner/r", _candidate(), db, gh_get=fake_gh)
        assert result.points_awarded == 5

    def test_partial_for_solo_no_codeowners(self, db):
        def fake_gh(path):
            if path == "repos/owner/r":
                return {"owner": {"type": "User"}}
            if "contributors" in path:
                return [{"login": "solo"}]
            return None

        result = score_r4_maintainer_structure("owner/r", _candidate(), db, gh_get=fake_gh)
        assert result.points_awarded == 2


# ---------------------------------------------------------------------------
# R5 (#309): license permissive
# ---------------------------------------------------------------------------


class TestScoreR5License:
    @pytest.mark.parametrize(
        "license_id,expected",
        [
            ("MIT", 5),
            ("Apache-2.0", 5),
            ("BSD-3-Clause", 5),
            ("MPL-2.0", 5),
            ("ISC", 5),
            ("GPL-3.0", 2),
            ("AGPL-3.0", 2),
            (None, 0),
        ],
    )
    def test_license_tiers(self, db, monkeypatch, license_id, expected):
        monkeypatch.setattr(
            "gh_link_auditor.preflight.scores.fetch_repo_metadata",
            lambda owner, name: RepoQuality(license=license_id),
        )
        result = score_r5_license("owner/r", _candidate(), db)
        assert result.points_awarded == expected
