"""Tests for bulk_scan.investigation pure-function bits (#218)."""

from __future__ import annotations

from gh_link_auditor.bulk_scan.investigation import (
    compute_confidence,
    filter_tier1,
)


class TestFilterTier1:
    def test_keeps_verified_tier1(self) -> None:
        cands = [{"method": "url_mutation", "verified_live": True, "tier": 1}]
        assert len(filter_tier1(cands)) == 1

    def test_drops_unverified_tier1(self) -> None:
        cands = [{"method": "url_mutation", "verified_live": False, "tier": 1}]
        assert filter_tier1(cands) == []

    def test_drops_redirect_chain(self) -> None:
        # redirect_chain candidates are suppressed per #197 — never tier-1 in bulk
        cands = [{"method": "redirect_chain", "verified_live": True, "tier": 1}]
        assert filter_tier1(cands) == []

    def test_drops_sitemap_search(self) -> None:
        cands = [{"method": "sitemap_search", "verified_live": True, "tier": 2}]
        assert filter_tier1(cands) == []

    def test_drops_archive_only(self) -> None:
        cands = [{"method": "archive_only", "verified_live": False, "tier": 2}]
        assert filter_tier1(cands) == []

    def test_keeps_github_api_redirect(self) -> None:
        cands = [{"method": "github_api_redirect", "verified_live": True, "tier": 1}]
        assert len(filter_tier1(cands)) == 1

    def test_keeps_wikipedia_suggest(self) -> None:
        cands = [{"method": "wikipedia_suggest", "verified_live": True, "tier": 1}]
        assert len(filter_tier1(cands)) == 1


class TestComputeConfidence:
    def test_verified_url_mutation_strong(self) -> None:
        c = {"method": "url_mutation", "verified_live": True, "similarity_score": 0.9}
        score = compute_confidence(c)
        assert score >= 0.85

    def test_verified_github_api_redirect_very_strong(self) -> None:
        c = {"method": "github_api_redirect", "verified_live": True, "similarity_score": 1.0}
        score = compute_confidence(c)
        assert score >= 0.95

    def test_unverified_penalized(self) -> None:
        c = {"method": "url_mutation", "verified_live": False, "similarity_score": 0.9}
        score = compute_confidence(c)
        assert score < 0.85

    def test_clipped_to_one(self) -> None:
        c = {
            "method": "github_api_redirect",
            "verified_live": True,
            "similarity_score": 100.0,  # silly
        }
        assert compute_confidence(c) <= 1.0

    def test_clipped_to_zero(self) -> None:
        c = {"method": "unknown_method", "verified_live": False, "similarity_score": None}
        assert compute_confidence(c) >= 0.0

    def test_none_similarity_treated_as_zero(self) -> None:
        c = {"method": "url_mutation", "verified_live": True, "similarity_score": None}
        score = compute_confidence(c)
        assert 0.85 <= score <= 0.95
