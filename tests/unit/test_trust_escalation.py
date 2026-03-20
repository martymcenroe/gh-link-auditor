"""Tests for trust-based PR escalation with tier 1/tier 2 fix levels.

Covers:
- Trust state machine in unified_db (get/update/check_tier2/get_tier1_proven)
- Tier tagging in n2_investigate (classify_tier)
- Fix filtering in graph._pr_preview_gate and _filter_fixes_by_trust
- Trust tracking in pr_tracker (_update_trust_on_merge, upgrade_tier1_proven_repos)

See Issue #149 for specification.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from gh_link_auditor.pipeline.nodes.n2_investigate import classify_tier
from gh_link_auditor.pipeline.state import (
    DeadLink,
    FixPatch,
    ReplacementCandidate,
    Verdict,
    create_initial_state,
)
from gh_link_auditor.unified_db import UnifiedDatabase

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    with UnifiedDatabase(":memory:") as database:
        yield database


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dead_link(url: str = "https://dead.com/page") -> DeadLink:
    return DeadLink(
        url=url,
        source_file="README.md",
        line_number=10,
        link_text="link",
        http_status=404,
        error_type="http_error",
    )


def _make_candidate(
    url: str = "https://new.com/page",
    source: str = "redirect_chain",
    tier: int = 1,
) -> ReplacementCandidate:
    return ReplacementCandidate(
        url=url,
        source=source,
        title=None,
        snippet=None,
        tier=tier,
    )


def _make_verdict(
    dead_url: str = "https://dead.com/page",
    candidate_url: str = "https://new.com/page",
    candidate_tier: int = 1,
    confidence: float = 0.95,
) -> Verdict:
    return Verdict(
        dead_link=_make_dead_link(dead_url),
        candidate=_make_candidate(url=candidate_url, tier=candidate_tier),
        confidence=confidence,
        reasoning="test",
        approved=True,
    )


def _make_fix(
    original_url: str = "https://dead.com/page",
    replacement_url: str = "https://new.com/page",
) -> FixPatch:
    return FixPatch(
        source_file="README.md",
        original_url=original_url,
        replacement_url=replacement_url,
        unified_diff="--- a/README.md\n+++ b/README.md",
    )


# ===========================================================================
# Trust State Machine (unified_db.py)
# ===========================================================================


class TestGetRepoTrust:
    """Tests for UnifiedDatabase.get_repo_trust()."""

    def test_returns_none_for_unknown_repo(self, db) -> None:
        assert db.get_repo_trust("unknown/repo") is None

    def test_returns_trust_after_update(self, db) -> None:
        db.update_repo_trust("owner/repo", "new")
        trust = db.get_repo_trust("owner/repo")
        assert trust is not None
        assert trust["trust_level"] == "new"

    def test_returns_all_fields(self, db) -> None:
        db.update_repo_trust(
            "owner/repo",
            "tier1_proven",
            first_pr_at="2026-01-01T00:00:00+00:00",
            first_merge_at="2026-01-15T00:00:00+00:00",
            total_prs=3,
            total_merges=1,
        )
        trust = db.get_repo_trust("owner/repo")
        assert trust is not None
        assert trust["trust_level"] == "tier1_proven"
        assert trust["first_pr_at"] == "2026-01-01T00:00:00+00:00"
        assert trust["first_merge_at"] == "2026-01-15T00:00:00+00:00"
        assert trust["total_prs"] == 3
        assert trust["total_merges"] == 1
        assert trust["is_blacklisted"] == 0


class TestUpdateRepoTrust:
    """Tests for UnifiedDatabase.update_repo_trust()."""

    def test_creates_new_record(self, db) -> None:
        db.update_repo_trust("owner/repo", "new")
        trust = db.get_repo_trust("owner/repo")
        assert trust is not None
        assert trust["trust_level"] == "new"
        assert trust["total_prs"] == 0
        assert trust["total_merges"] == 0

    def test_updates_existing_record(self, db) -> None:
        db.update_repo_trust("owner/repo", "new")
        db.update_repo_trust("owner/repo", "tier1_pending", total_prs=1)
        trust = db.get_repo_trust("owner/repo")
        assert trust["trust_level"] == "tier1_pending"
        assert trust["total_prs"] == 1

    def test_creates_repo_if_not_exists(self, db) -> None:
        """update_repo_trust should create the repo in repos table."""
        db.update_repo_trust("new/repo", "new")
        repo = db.get_repo("new/repo")
        assert repo is not None

    def test_preserves_existing_fields_on_partial_update(self, db) -> None:
        db.update_repo_trust(
            "owner/repo",
            "tier1_proven",
            first_merge_at="2026-01-15T00:00:00+00:00",
            total_prs=2,
            total_merges=1,
        )
        # Update only trust_level and total_merges
        db.update_repo_trust("owner/repo", "tier2_eligible", total_merges=2)
        trust = db.get_repo_trust("owner/repo")
        assert trust["trust_level"] == "tier2_eligible"
        assert trust["total_merges"] == 2
        # first_merge_at should be preserved
        assert trust["first_merge_at"] == "2026-01-15T00:00:00+00:00"

    def test_sets_blacklisted_flag(self, db) -> None:
        db.update_repo_trust("owner/repo", "new", is_blacklisted=True)
        trust = db.get_repo_trust("owner/repo")
        assert trust["is_blacklisted"] == 1

    def test_all_trust_levels(self, db) -> None:
        for level in ("new", "tier1_pending", "tier1_proven", "tier2_eligible"):
            db.update_repo_trust(f"owner/{level}", level)
            trust = db.get_repo_trust(f"owner/{level}")
            assert trust["trust_level"] == level


class TestCheckTier2Eligibility:
    """Tests for UnifiedDatabase.check_tier2_eligibility()."""

    def test_no_trust_record_returns_false(self, db) -> None:
        assert db.check_tier2_eligibility("unknown/repo") is False

    def test_new_repo_returns_false(self, db) -> None:
        db.update_repo_trust("owner/repo", "new")
        assert db.check_tier2_eligibility("owner/repo") is False

    def test_tier1_pending_returns_false(self, db) -> None:
        db.update_repo_trust("owner/repo", "tier1_pending")
        assert db.check_tier2_eligibility("owner/repo") is False

    def test_tier1_proven_without_merge_date_returns_false(self, db) -> None:
        db.update_repo_trust("owner/repo", "tier1_proven")
        assert db.check_tier2_eligibility("owner/repo") is False

    def test_tier1_proven_under_14_days_returns_false(self, db) -> None:
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        db.update_repo_trust("owner/repo", "tier1_proven", first_merge_at=recent)
        assert db.check_tier2_eligibility("owner/repo") is False

    def test_tier1_proven_over_14_days_returns_true(self, db) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        db.update_repo_trust("owner/repo", "tier1_proven", first_merge_at=old)
        assert db.check_tier2_eligibility("owner/repo") is True

    def test_already_tier2_returns_true(self, db) -> None:
        db.update_repo_trust("owner/repo", "tier2_eligible")
        assert db.check_tier2_eligibility("owner/repo") is True

    def test_exactly_14_days_returns_true(self, db) -> None:
        exactly_14 = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        db.update_repo_trust("owner/repo", "tier1_proven", first_merge_at=exactly_14)
        assert db.check_tier2_eligibility("owner/repo") is True


class TestGetTier1ProvenRepos:
    """Tests for UnifiedDatabase.get_tier1_proven_repos()."""

    def test_empty_database(self, db) -> None:
        assert db.get_tier1_proven_repos() == []

    def test_returns_only_tier1_proven(self, db) -> None:
        db.update_repo_trust("a/new", "new")
        db.update_repo_trust("b/pending", "tier1_pending")
        db.update_repo_trust("c/proven", "tier1_proven")
        db.update_repo_trust("d/eligible", "tier2_eligible")

        results = db.get_tier1_proven_repos()
        assert len(results) == 1
        assert results[0]["full_name"] == "c/proven"

    def test_returns_multiple_proven_repos(self, db) -> None:
        db.update_repo_trust("a/repo1", "tier1_proven")
        db.update_repo_trust("b/repo2", "tier1_proven")
        results = db.get_tier1_proven_repos()
        assert len(results) == 2


# ===========================================================================
# Tier Tagging (n2_investigate.py)
# ===========================================================================


class TestClassifyTier:
    """Tests for classify_tier()."""

    def test_redirect_chain_verified_is_tier1(self) -> None:
        assert classify_tier("redirect_chain", verified_live=True) == 1

    def test_url_mutation_verified_is_tier1(self) -> None:
        assert classify_tier("url_mutation", verified_live=True) == 1

    def test_strip_index_verified_is_tier1(self) -> None:
        assert classify_tier("strip_index", verified_live=True) == 1

    def test_wikipedia_suggest_verified_is_tier1(self) -> None:
        assert classify_tier("wikipedia_suggest", verified_live=True) == 1

    def test_github_api_redirect_verified_is_tier1(self) -> None:
        assert classify_tier("github_api_redirect", verified_live=True) == 1

    def test_redirect_chain_unverified_is_tier2(self) -> None:
        assert classify_tier("redirect_chain", verified_live=False) == 2

    def test_sitemap_search_verified_is_tier2(self) -> None:
        assert classify_tier("sitemap_search", verified_live=True) == 2

    def test_url_heuristic_verified_is_tier2(self) -> None:
        assert classify_tier("url_heuristic", verified_live=True) == 2

    def test_unknown_method_is_tier2(self) -> None:
        assert classify_tier("some_new_method", verified_live=True) == 2

    def test_sitemap_search_unverified_is_tier2(self) -> None:
        assert classify_tier("sitemap_search", verified_live=False) == 2


class TestInvestigateDeadLinkTierTagging:
    """Tests that investigate_dead_link() adds tier annotations."""

    def test_tier_added_to_candidates(self) -> None:
        from gh_link_auditor.link_detective import (
            CandidateReplacement,
            ForensicReport,
            Investigation,
            InvestigationMethod,
        )
        from gh_link_auditor.pipeline.nodes.n2_investigate import investigate_dead_link

        report = ForensicReport(
            dead_url="https://dead.com/page",
            http_status=404,
            investigation=Investigation(
                archive_snapshot=None,
                archive_title="Title",
                archive_content_summary="Summary",
                candidate_replacements=[
                    CandidateReplacement(
                        url="https://new.com/page",
                        method=InvestigationMethod.REDIRECT_CHAIN,
                        similarity_score=0.95,
                        verified_live=True,
                    ),
                    CandidateReplacement(
                        url="https://guess.com/page",
                        method=InvestigationMethod.SITEMAP_SEARCH,
                        similarity_score=0.6,
                        verified_live=True,
                    ),
                ],
                investigation_log=["test"],
            ),
        )
        with patch(
            "gh_link_auditor.pipeline.nodes.n2_investigate._run_investigation",
            return_value=report,
        ):
            candidates = investigate_dead_link(_make_dead_link())

        assert len(candidates) == 2
        assert candidates[0]["tier"] == 1  # redirect_chain + verified
        assert candidates[1]["tier"] == 2  # sitemap_search = always tier 2

    def test_unverified_tier1_method_becomes_tier2(self) -> None:
        from gh_link_auditor.link_detective import (
            CandidateReplacement,
            ForensicReport,
            Investigation,
            InvestigationMethod,
        )
        from gh_link_auditor.pipeline.nodes.n2_investigate import investigate_dead_link

        report = ForensicReport(
            dead_url="https://dead.com/page",
            http_status=404,
            investigation=Investigation(
                archive_snapshot=None,
                archive_title=None,
                archive_content_summary=None,
                candidate_replacements=[
                    CandidateReplacement(
                        url="https://new.com/page",
                        method=InvestigationMethod.REDIRECT_CHAIN,
                        similarity_score=0.7,
                        verified_live=False,  # unverified!
                    ),
                ],
                investigation_log=["test"],
            ),
        )
        with patch(
            "gh_link_auditor.pipeline.nodes.n2_investigate._run_investigation",
            return_value=report,
        ):
            candidates = investigate_dead_link(_make_dead_link())

        assert len(candidates) == 1
        assert candidates[0]["tier"] == 2  # unverified -> tier 2


# ===========================================================================
# Fix Filtering (graph.py)
# ===========================================================================


class TestFilterFixesByTrust:
    """Tests for _filter_fixes_by_trust()."""

    def test_tier2_excluded_for_new_repo(self) -> None:
        from gh_link_auditor.pipeline.graph import _filter_fixes_by_trust

        fixes = [
            _make_fix("https://dead.com/a", "https://new.com/a"),
            _make_fix("https://dead.com/b", "https://new.com/b"),
        ]
        candidates = {
            "https://dead.com/a": [_make_candidate(tier=1)],
            "https://dead.com/b": [_make_candidate(tier=2)],
        }
        verdicts = [
            _make_verdict("https://dead.com/a", candidate_tier=1),
            _make_verdict("https://dead.com/b", candidate_tier=2),
        ]

        filtered, excluded = _filter_fixes_by_trust(fixes, verdicts, candidates, "new")
        assert len(filtered) == 1
        assert filtered[0]["original_url"] == "https://dead.com/a"
        assert excluded == 1

    def test_tier2_excluded_for_tier1_pending(self) -> None:
        from gh_link_auditor.pipeline.graph import _filter_fixes_by_trust

        fixes = [_make_fix("https://dead.com/a", "https://new.com/a")]
        candidates = {
            "https://dead.com/a": [_make_candidate(tier=2)],
        }
        verdicts = [_make_verdict("https://dead.com/a", candidate_tier=2)]

        filtered, excluded = _filter_fixes_by_trust(fixes, verdicts, candidates, "tier1_pending")
        assert len(filtered) == 0
        assert excluded == 1

    def test_nothing_excluded_for_tier1_proven(self) -> None:
        from gh_link_auditor.pipeline.graph import _filter_fixes_by_trust

        fixes = [_make_fix("https://dead.com/a", "https://new.com/a")]
        candidates = {
            "https://dead.com/a": [_make_candidate(tier=2)],
        }
        verdicts = [_make_verdict("https://dead.com/a", candidate_tier=2)]

        filtered, excluded = _filter_fixes_by_trust(fixes, verdicts, candidates, "tier1_proven")
        assert len(filtered) == 1
        assert excluded == 0

    def test_nothing_excluded_for_tier2_eligible(self) -> None:
        from gh_link_auditor.pipeline.graph import _filter_fixes_by_trust

        fixes = [_make_fix("https://dead.com/a", "https://new.com/a")]
        candidates = {
            "https://dead.com/a": [_make_candidate(tier=2)],
        }
        verdicts = [_make_verdict("https://dead.com/a", candidate_tier=2)]

        filtered, excluded = _filter_fixes_by_trust(fixes, verdicts, candidates, "tier2_eligible")
        assert len(filtered) == 1
        assert excluded == 0

    def test_tier1_fixes_always_pass(self) -> None:
        from gh_link_auditor.pipeline.graph import _filter_fixes_by_trust

        fixes = [_make_fix("https://dead.com/a", "https://new.com/a")]
        candidates = {
            "https://dead.com/a": [_make_candidate(tier=1)],
        }
        verdicts = [_make_verdict("https://dead.com/a", candidate_tier=1)]

        filtered, excluded = _filter_fixes_by_trust(fixes, verdicts, candidates, "new")
        assert len(filtered) == 1
        assert excluded == 0

    def test_empty_fixes_returns_empty(self) -> None:
        from gh_link_auditor.pipeline.graph import _filter_fixes_by_trust

        filtered, excluded = _filter_fixes_by_trust([], [], {}, "new")
        assert filtered == []
        assert excluded == 0

    def test_mixed_tier_filtering(self) -> None:
        from gh_link_auditor.pipeline.graph import _filter_fixes_by_trust

        fixes = [
            _make_fix("https://dead.com/a", "https://new.com/a"),
            _make_fix("https://dead.com/b", "https://new.com/b"),
            _make_fix("https://dead.com/c", "https://new.com/c"),
        ]
        candidates = {
            "https://dead.com/a": [_make_candidate(tier=1)],
            "https://dead.com/b": [_make_candidate(tier=2)],
            "https://dead.com/c": [_make_candidate(tier=1)],
        }
        verdicts = [
            _make_verdict("https://dead.com/a", candidate_tier=1),
            _make_verdict("https://dead.com/b", candidate_tier=2),
            _make_verdict("https://dead.com/c", candidate_tier=1),
        ]

        filtered, excluded = _filter_fixes_by_trust(fixes, verdicts, candidates, "new")
        assert len(filtered) == 2
        assert excluded == 1
        urls = [f["original_url"] for f in filtered]
        assert "https://dead.com/a" in urls
        assert "https://dead.com/c" in urls


class TestGetRepoTrustLevel:
    """Tests for _get_repo_trust_level()."""

    def test_returns_new_for_local_target(self) -> None:
        from gh_link_auditor.pipeline.graph import _get_repo_trust_level

        state = create_initial_state(target="/local/path")
        state["target_type"] = "local"
        assert _get_repo_trust_level(state) == "new"

    def test_returns_new_for_missing_owner(self) -> None:
        from gh_link_auditor.pipeline.graph import _get_repo_trust_level

        state = create_initial_state(target="https://github.com/o/r")
        state["target_type"] = "url"
        state["repo_owner"] = ""
        assert _get_repo_trust_level(state) == "new"

    def test_returns_trust_from_db(self, tmp_path) -> None:
        from gh_link_auditor.pipeline.graph import _get_repo_trust_level

        db_path = str(tmp_path / "test.db")
        with UnifiedDatabase(db_path) as udb:
            udb.update_repo_trust("org/repo", "tier1_proven")

        state = create_initial_state(target="https://github.com/org/repo")
        state["target_type"] = "url"
        state["repo_owner"] = "org"
        state["repo_name_short"] = "repo"
        state["db_path"] = db_path

        assert _get_repo_trust_level(state) == "tier1_proven"

    def test_returns_new_on_db_error(self) -> None:
        from gh_link_auditor.pipeline.graph import _get_repo_trust_level

        state = create_initial_state(target="https://github.com/org/repo")
        state["target_type"] = "url"
        state["repo_owner"] = "org"
        state["repo_name_short"] = "repo"
        state["db_path"] = "/nonexistent/path/db.sqlite"

        # Should not raise, just return "new"
        assert _get_repo_trust_level(state) == "new"


class TestPrPreviewGateTrustFiltering:
    """Tests for _pr_preview_gate() trust-based fix filtering."""

    def test_filters_tier2_for_new_repo(self) -> None:
        from gh_link_auditor.pipeline.graph import _pr_preview_gate

        state = create_initial_state(target="t")
        state["fixes"] = [
            _make_fix("https://dead.com/a", "https://new.com/a"),
            _make_fix("https://dead.com/b", "https://new.com/b"),
        ]
        state["candidates"] = {
            "https://dead.com/a": [_make_candidate(tier=1)],
            "https://dead.com/b": [_make_candidate(tier=2)],
        }
        state["verdicts"] = [
            _make_verdict("https://dead.com/a", candidate_tier=1),
            _make_verdict("https://dead.com/b", candidate_tier=2),
        ]

        with (
            patch(
                "gh_link_auditor.pipeline.graph._get_repo_trust_level",
                return_value="new",
            ),
            patch("builtins.input", return_value="y"),
        ):
            result = _pr_preview_gate(state)

        assert result["tier2_fixes_excluded"] == 1
        assert len(result["fixes"]) == 1
        assert result["pr_preview_approved"] is True

    def test_all_tier2_excluded_not_approved(self) -> None:
        from gh_link_auditor.pipeline.graph import _pr_preview_gate

        state = create_initial_state(target="t")
        state["fixes"] = [_make_fix("https://dead.com/a", "https://new.com/a")]
        state["candidates"] = {
            "https://dead.com/a": [_make_candidate(tier=2)],
        }
        state["verdicts"] = [
            _make_verdict("https://dead.com/a", candidate_tier=2),
        ]

        with patch(
            "gh_link_auditor.pipeline.graph._get_repo_trust_level",
            return_value="new",
        ):
            result = _pr_preview_gate(state)

        assert result["pr_preview_approved"] is False
        assert result["tier2_fixes_excluded"] == 1
        assert len(result["fixes"]) == 0

    def test_no_filtering_for_proven_repo(self) -> None:
        from gh_link_auditor.pipeline.graph import _pr_preview_gate

        state = create_initial_state(target="t")
        state["fixes"] = [_make_fix("https://dead.com/a", "https://new.com/a")]
        state["candidates"] = {
            "https://dead.com/a": [_make_candidate(tier=2)],
        }
        state["verdicts"] = [
            _make_verdict("https://dead.com/a", candidate_tier=2),
        ]

        with (
            patch(
                "gh_link_auditor.pipeline.graph._get_repo_trust_level",
                return_value="tier1_proven",
            ),
            patch("builtins.input", return_value="y"),
        ):
            result = _pr_preview_gate(state)

        assert result["tier2_fixes_excluded"] == 0
        assert len(result["fixes"]) == 1
        assert result["pr_preview_approved"] is True


# ===========================================================================
# Trust Tracking (pr_tracker.py)
# ===========================================================================


class TestUpdateTrustOnMerge:
    """Tests for _update_trust_on_merge()."""

    def test_creates_trust_for_unknown_repo(self, db) -> None:
        from gh_link_auditor.pr_tracker import _update_trust_on_merge

        merged_at = datetime(2026, 3, 15, tzinfo=timezone.utc)
        _update_trust_on_merge(db, "org/repo", merged_at)

        trust = db.get_repo_trust("org/repo")
        assert trust is not None
        assert trust["trust_level"] == "tier1_proven"
        assert trust["total_merges"] == 1

    def test_transitions_new_to_tier1_proven(self, db) -> None:
        from gh_link_auditor.pr_tracker import _update_trust_on_merge

        db.update_repo_trust("org/repo", "new")
        merged_at = datetime(2026, 3, 15, tzinfo=timezone.utc)
        _update_trust_on_merge(db, "org/repo", merged_at)

        trust = db.get_repo_trust("org/repo")
        assert trust["trust_level"] == "tier1_proven"
        assert trust["total_merges"] == 1

    def test_transitions_tier1_pending_to_tier1_proven(self, db) -> None:
        from gh_link_auditor.pr_tracker import _update_trust_on_merge

        db.update_repo_trust("org/repo", "tier1_pending", total_prs=1)
        merged_at = datetime(2026, 3, 15, tzinfo=timezone.utc)
        _update_trust_on_merge(db, "org/repo", merged_at)

        trust = db.get_repo_trust("org/repo")
        assert trust["trust_level"] == "tier1_proven"

    def test_increments_merges_for_tier1_proven(self, db) -> None:
        from gh_link_auditor.pr_tracker import _update_trust_on_merge

        db.update_repo_trust(
            "org/repo",
            "tier1_proven",
            total_merges=1,
            first_merge_at="2026-01-01T00:00:00+00:00",
        )
        merged_at = datetime(2026, 3, 15, tzinfo=timezone.utc)
        _update_trust_on_merge(db, "org/repo", merged_at)

        trust = db.get_repo_trust("org/repo")
        assert trust["trust_level"] == "tier1_proven"
        assert trust["total_merges"] == 2

    def test_increments_merges_for_tier2_eligible(self, db) -> None:
        from gh_link_auditor.pr_tracker import _update_trust_on_merge

        db.update_repo_trust("org/repo", "tier2_eligible", total_merges=3)
        merged_at = datetime(2026, 3, 15, tzinfo=timezone.utc)
        _update_trust_on_merge(db, "org/repo", merged_at)

        trust = db.get_repo_trust("org/repo")
        assert trust["trust_level"] == "tier2_eligible"
        assert trust["total_merges"] == 4


class TestUpgradeTier1ProvenRepos:
    """Tests for upgrade_tier1_proven_repos()."""

    def test_upgrades_eligible_repos(self, db) -> None:
        from gh_link_auditor.pr_tracker import upgrade_tier1_proven_repos

        old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        db.update_repo_trust("org/repo", "tier1_proven", first_merge_at=old)

        upgraded = upgrade_tier1_proven_repos(db)
        assert "org/repo" in upgraded

        trust = db.get_repo_trust("org/repo")
        assert trust["trust_level"] == "tier2_eligible"

    def test_skips_repos_under_14_days(self, db) -> None:
        from gh_link_auditor.pr_tracker import upgrade_tier1_proven_repos

        recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        db.update_repo_trust("org/repo", "tier1_proven", first_merge_at=recent)

        upgraded = upgrade_tier1_proven_repos(db)
        assert upgraded == []

        trust = db.get_repo_trust("org/repo")
        assert trust["trust_level"] == "tier1_proven"

    def test_skips_non_proven_repos(self, db) -> None:
        from gh_link_auditor.pr_tracker import upgrade_tier1_proven_repos

        db.update_repo_trust("a/new", "new")
        db.update_repo_trust("b/pending", "tier1_pending")
        db.update_repo_trust("c/eligible", "tier2_eligible")

        upgraded = upgrade_tier1_proven_repos(db)
        assert upgraded == []

    def test_empty_database(self, db) -> None:
        from gh_link_auditor.pr_tracker import upgrade_tier1_proven_repos

        upgraded = upgrade_tier1_proven_repos(db)
        assert upgraded == []

    def test_upgrades_multiple_repos(self, db) -> None:
        from gh_link_auditor.pr_tracker import upgrade_tier1_proven_repos

        old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        db.update_repo_trust("a/repo1", "tier1_proven", first_merge_at=old)
        db.update_repo_trust("b/repo2", "tier1_proven", first_merge_at=old)

        upgraded = upgrade_tier1_proven_repos(db)
        assert len(upgraded) == 2
        assert "a/repo1" in upgraded
        assert "b/repo2" in upgraded


class TestRefreshPrOutcomesTrustIntegration:
    """Integration tests: refresh_pr_outcomes updates trust on merge."""

    def test_merged_pr_creates_trust_record(self, tmp_path) -> None:
        from gh_link_auditor.metrics.collector import MetricsCollector
        from gh_link_auditor.metrics.models import PROutcome
        from gh_link_auditor.pr_tracker import refresh_pr_outcomes

        db_path = tmp_path / "metrics.db"
        collector = MetricsCollector(db_path)
        collector.record_pr_outcome(
            PROutcome(
                pr_url="https://github.com/org/repo/pull/10",
                repo_full_name="org/repo",
                submitted_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
                status="open",
            )
        )
        collector.close()

        api_response = {
            "state": "closed",
            "merged": True,
            "merged_at": "2026-03-15T12:00:00Z",
            "closed_at": None,
        }

        with patch(
            "gh_link_auditor.pr_tracker._fetch_pr_status",
            return_value=api_response,
        ):
            refresh_pr_outcomes(db_path)

        udb = UnifiedDatabase(db_path)
        try:
            trust = udb.get_repo_trust("org/repo")
            assert trust is not None
            assert trust["trust_level"] == "tier1_proven"
            assert trust["total_merges"] == 1
        finally:
            udb.close()

    def test_refresh_upgrades_eligible_repos(self, tmp_path) -> None:
        from gh_link_auditor.metrics.collector import MetricsCollector
        from gh_link_auditor.metrics.models import PROutcome
        from gh_link_auditor.pr_tracker import refresh_pr_outcomes

        db_path = tmp_path / "metrics.db"

        # Seed a tier1_proven repo that's past 14 days
        udb = UnifiedDatabase(db_path)
        old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        udb.update_repo_trust("org/repo", "tier1_proven", first_merge_at=old)
        udb.close()

        # Seed an open PR for a different repo so refresh actually runs
        collector = MetricsCollector(db_path)
        collector.record_pr_outcome(
            PROutcome(
                pr_url="https://github.com/other/repo/pull/5",
                repo_full_name="other/repo",
                submitted_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
                status="open",
            )
        )
        collector.close()

        api_response = {
            "state": "open",
            "merged": False,
            "merged_at": None,
            "closed_at": None,
        }

        with patch(
            "gh_link_auditor.pr_tracker._fetch_pr_status",
            return_value=api_response,
        ):
            refresh_pr_outcomes(db_path)

        udb = UnifiedDatabase(db_path)
        try:
            trust = udb.get_repo_trust("org/repo")
            assert trust is not None
            assert trust["trust_level"] == "tier2_eligible"
        finally:
            udb.close()


# ===========================================================================
# ReplacementCandidate TypedDict tier field
# ===========================================================================


class TestReplacementCandidateTier:
    """Tests that ReplacementCandidate supports the tier field."""

    def test_tier_field_present(self) -> None:
        c = ReplacementCandidate(
            url="https://new.com",
            source="redirect_chain",
            title=None,
            snippet=None,
            tier=1,
        )
        assert c["tier"] == 1

    def test_tier_field_optional(self) -> None:
        # total=False means all fields are optional
        c: ReplacementCandidate = {"url": "https://new.com", "source": "redirect_chain"}  # type: ignore[typeddict-item]
        assert "tier" not in c

    def test_tier2_candidate(self) -> None:
        c = ReplacementCandidate(
            url="https://guess.com",
            source="url_heuristic",
            title=None,
            snippet=None,
            tier=2,
        )
        assert c["tier"] == 2
