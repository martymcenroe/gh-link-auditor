"""Unit tests for link investigation orchestrator (LLD #20, §10.0).

TDD: Tests written BEFORE implementation.
Covers: LinkDetective.investigate(), data structures, cache, pipeline flow.
"""

from unittest.mock import patch

import pytest

from gh_link_auditor.link_detective import (
    CandidateReplacement,
    ForensicReport,
    Investigation,
    InvestigationMethod,
    LinkDetective,
)
from tests.fakes.archive import make_archive_hit, make_archive_miss
from tests.fakes.detectives import FakeGitHubResolver, FakeRedirectResolver, FakeURLHeuristic
from tests.fakes.http import FakeURLResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_detective(state_db=None) -> LinkDetective:
    """Build a LinkDetective with a None state_db."""
    return LinkDetective(state_db=state_db)


# ---------------------------------------------------------------------------
# T010: investigate() returns ForensicReport (REQ-1)
# ---------------------------------------------------------------------------


class TestInvestigateReturnsReport:
    def test_returns_forensic_report(self):
        """investigate() returns a ForensicReport with all required fields."""
        detective = _make_detective()
        detective._redirect_resolver = FakeRedirectResolver()
        detective._archive_client = make_archive_miss()
        detective._url_heuristic = FakeURLHeuristic()
        detective._github_resolver = FakeGitHubResolver()

        report = detective.investigate("https://dead.example.com/page", 404)

        assert isinstance(report, ForensicReport)
        assert report.dead_url == "https://dead.example.com/page"
        assert report.http_status == 404
        assert isinstance(report.investigation, Investigation)
        assert isinstance(report.investigation.candidate_replacements, list)
        assert isinstance(report.investigation.investigation_log, list)


# ---------------------------------------------------------------------------
# T120: Invalid scheme rejected (REQ-9)
# ---------------------------------------------------------------------------


class TestInvalidScheme:
    def test_ftp_scheme_raises(self):
        detective = _make_detective()
        with pytest.raises(ValueError, match="http"):
            detective.investigate("ftp://example.com/file", 404)

    def test_no_scheme_raises(self):
        detective = _make_detective()
        with pytest.raises(ValueError):
            detective.investigate("not-a-url", 404)


# ---------------------------------------------------------------------------
# T040: Redirect chain produces candidate (REQ-3)
# ---------------------------------------------------------------------------


class TestRedirectCandidate:
    def test_redirect_chain_short_circuits(self):
        """High-confidence redirect produces early return."""
        detective = _make_detective()
        detective._redirect_resolver = FakeRedirectResolver(
            redirect_map={"https://old.com/page": ("https://new.com/page", ["301 -> https://new.com/page"])},
            live_urls={"https://new.com/page"},
        )
        detective._archive_client = make_archive_miss()
        detective._url_heuristic = FakeURLHeuristic()
        detective._github_resolver = FakeGitHubResolver()

        report = detective.investigate("https://old.com/page", 301)

        candidates = report.investigation.candidate_replacements
        assert len(candidates) >= 1
        assert candidates[0].method == InvestigationMethod.REDIRECT_CHAIN
        assert candidates[0].verified_live is True


# ---------------------------------------------------------------------------
# T030: Archive miss continues (REQ-2)
# ---------------------------------------------------------------------------


class TestArchiveMiss:
    def test_archive_miss_continues_investigation(self):
        """No archive snapshot — investigation_log records it, continues."""
        detective = _make_detective()
        detective._redirect_resolver = FakeRedirectResolver()
        detective._archive_client = make_archive_miss()
        detective._url_heuristic = FakeURLHeuristic()
        detective._github_resolver = FakeGitHubResolver()

        report = detective.investigate("https://dead.example.com", 404)

        assert any("no archive" in entry.lower() for entry in report.investigation.investigation_log)


# ---------------------------------------------------------------------------
# T130: Candidates sorted by score descending (REQ-10)
# ---------------------------------------------------------------------------


class TestCandidateSorting:
    def test_candidates_sorted_descending(self):
        """Multiple candidates are sorted by similarity_score descending."""
        detective = _make_detective()
        detective._redirect_resolver = FakeRedirectResolver(
            mutations={"https://example.com/docs": [("https://example.com/docs-new", "trailing_slash")]},
            live_urls={"https://example.com/docs-new"},
        )
        detective._archive_client = make_archive_hit()
        detective._url_heuristic = FakeURLHeuristic(
            candidates=["https://example.com/example-docs"],
            live=["https://example.com/example-docs"],
        )
        detective._github_resolver = FakeGitHubResolver()

        # Mock content fetch for similarity comparison
        with patch(
            "gh_link_auditor.link_detective._fetch_page_content",
            return_value="Content here similar",
        ):
            with patch(
                "gh_link_auditor.link_detective.compute_similarity",
                return_value=0.7,
            ):
                report = detective.investigate("https://example.com/docs", 404)

        candidates = report.investigation.candidate_replacements
        if len(candidates) >= 2:
            scores = [c.similarity_score for c in candidates]
            assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# T140: No candidates returns empty (REQ-1)
# ---------------------------------------------------------------------------


class TestNoCandidates:
    def test_empty_candidates_when_nothing_found(self):
        """Returns empty candidate list when no matches found anywhere."""
        detective = _make_detective()
        detective._redirect_resolver = FakeRedirectResolver()
        detective._archive_client = make_archive_miss()
        detective._url_heuristic = FakeURLHeuristic()
        detective._github_resolver = FakeGitHubResolver()

        report = detective.investigate("https://totally-gone.example.com", 404)

        assert report.investigation.candidate_replacements == []
        assert len(report.investigation.investigation_log) > 0


# ---------------------------------------------------------------------------
# T100: Cache hit skips external calls (REQ-7)
# ---------------------------------------------------------------------------


class TestCaching:
    def test_cache_hit_returns_without_external_calls(self):
        """Second investigation of same URL uses cache."""
        detective = _make_detective()

        cached_report = ForensicReport(
            dead_url="https://cached.com",
            http_status=404,
            investigation=Investigation(
                archive_snapshot=None,
                archive_title=None,
                archive_content_summary=None,
                candidate_replacements=[],
                investigation_log=["cached"],
            ),
        )

        with patch.object(detective, "_check_cache", return_value=cached_report):
            report = detective.investigate("https://cached.com", 404)

        assert report is cached_report


# ---------------------------------------------------------------------------
# Data structure tests
# ---------------------------------------------------------------------------


class TestDataStructures:
    def test_investigation_method_values(self):
        assert InvestigationMethod.REDIRECT_CHAIN.value == "redirect_chain"
        assert InvestigationMethod.URL_MUTATION.value == "url_mutation"
        assert InvestigationMethod.URL_HEURISTIC.value == "url_heuristic"
        assert InvestigationMethod.GITHUB_API_REDIRECT.value == "github_api_redirect"
        assert InvestigationMethod.ARCHIVE_ONLY.value == "archive_only"

    def test_candidate_replacement_creation(self):
        c = CandidateReplacement(
            url="https://example.com",
            method=InvestigationMethod.REDIRECT_CHAIN,
            similarity_score=0.98,
            verified_live=True,
        )
        assert c.url == "https://example.com"
        assert c.similarity_score == 0.98

    def test_forensic_report_creation(self):
        inv = Investigation(
            archive_snapshot=None,
            archive_title=None,
            archive_content_summary=None,
            candidate_replacements=[],
            investigation_log=[],
        )
        report = ForensicReport(dead_url="https://dead.com", http_status=404, investigation=inv)
        assert report.dead_url == "https://dead.com"


# ---------------------------------------------------------------------------
# Internal _fetch_page_content coverage
# ---------------------------------------------------------------------------


class TestFetchPageContent:
    def test_fetch_success(self):
        """_fetch_page_content returns decoded content."""
        from gh_link_auditor.link_detective import _fetch_page_content

        fake_resp = FakeURLResponse(b"page content")

        with patch("gh_link_auditor.link_detective.urllib.request.urlopen", return_value=fake_resp):
            result = _fetch_page_content("https://example.com")
        assert result == "page content"

    def test_fetch_error_returns_none(self):
        """_fetch_page_content returns None on network error."""
        from gh_link_auditor.link_detective import _fetch_page_content

        with patch(
            "gh_link_auditor.link_detective.urllib.request.urlopen",
            side_effect=OSError("connection refused"),
        ):
            result = _fetch_page_content("https://bad.example.com")
        assert result is None


# ---------------------------------------------------------------------------
# GitHub resolution path in pipeline
# ---------------------------------------------------------------------------


class TestGitHubResolutionInPipeline:
    def test_github_url_resolved(self):
        """GitHub URL triggers GitHub resolution in pipeline."""
        detective = _make_detective()
        detective._redirect_resolver = FakeRedirectResolver(
            live_urls={"https://github.com/new-owner/new-repo/blob/main/README.md"},
        )
        detective._archive_client = make_archive_miss()
        detective._url_heuristic = FakeURLHeuristic()
        detective._github_resolver = FakeGitHubResolver(
            redirects={"old-owner/old-repo": "https://github.com/new-owner/new-repo"},
        )

        report = detective.investigate("https://github.com/old-owner/old-repo/blob/main/README.md", 404)

        candidates = report.investigation.candidate_replacements
        github_candidates = [c for c in candidates if c.method == InvestigationMethod.GITHUB_API_REDIRECT]
        assert len(github_candidates) >= 1
        assert github_candidates[0].similarity_score == 1.0


# ---------------------------------------------------------------------------
# Archive-only fallback path
# ---------------------------------------------------------------------------


class TestArchiveOnlyFallback:
    def test_archive_only_when_no_live_candidates(self):
        """Archive-only fallback when snapshot exists but no live candidates."""
        detective = _make_detective()
        detective._redirect_resolver = FakeRedirectResolver()  # no live_urls
        detective._archive_client = make_archive_hit()
        detective._url_heuristic = FakeURLHeuristic()
        detective._github_resolver = FakeGitHubResolver()

        report = detective.investigate("https://dead.example.com/page", 404)

        candidates = report.investigation.candidate_replacements
        archive_only = [c for c in candidates if c.method == InvestigationMethod.ARCHIVE_ONLY]
        assert len(archive_only) >= 1
        assert archive_only[0].verified_live is False
        assert archive_only[0].similarity_score == 0.0


# ---------------------------------------------------------------------------
# URL heuristic with content similarity
# ---------------------------------------------------------------------------


class TestHeuristicWithSimilarity:
    def test_heuristic_below_threshold_excluded(self):
        """Heuristic candidate with similarity < 0.5 is excluded."""
        detective = _make_detective()
        detective._redirect_resolver = FakeRedirectResolver()
        detective._archive_client = make_archive_hit()
        detective._url_heuristic = FakeURLHeuristic(
            candidates=["https://example.com/different"],
            live=["https://example.com/different"],
        )
        detective._github_resolver = FakeGitHubResolver()

        with (
            patch(
                "gh_link_auditor.link_detective._fetch_page_content",
                return_value="Completely different content",
            ),
            patch(
                "gh_link_auditor.link_detective.compute_similarity",
                return_value=0.2,
            ),
        ):
            report = detective.investigate("https://dead.example.com/page", 404)

        heuristic_candidates = [
            c for c in report.investigation.candidate_replacements if c.method == InvestigationMethod.URL_HEURISTIC
        ]
        assert len(heuristic_candidates) == 0

    def test_heuristic_no_content_uses_low_score(self):
        """Heuristic candidate uses 0.3 score when page content unavailable."""
        detective = _make_detective()
        detective._redirect_resolver = FakeRedirectResolver()
        detective._archive_client = make_archive_hit()
        detective._url_heuristic = FakeURLHeuristic(
            candidates=["https://example.com/page"],
            live=["https://example.com/page"],
        )
        detective._github_resolver = FakeGitHubResolver()

        with patch(
            "gh_link_auditor.link_detective._fetch_page_content",
            return_value=None,
        ):
            report = detective.investigate("https://dead.example.com/page", 404)

        # Score 0.3 < 0.5 threshold, so candidate should NOT be included
        heuristic_candidates = [
            c for c in report.investigation.candidate_replacements if c.method == InvestigationMethod.URL_HEURISTIC
        ]
        assert len(heuristic_candidates) == 0


# ---------------------------------------------------------------------------
# Error handling in pipeline stages
# ---------------------------------------------------------------------------


class TestPipelineErrorHandling:
    def test_mutation_error_continues(self):
        """Exception in URL mutations doesn't stop the pipeline."""
        detective = _make_detective()
        detective._redirect_resolver = FakeRedirectResolver()
        detective._archive_client = make_archive_miss()
        detective._url_heuristic = FakeURLHeuristic()
        detective._github_resolver = FakeGitHubResolver()

        # Override test_url_mutations to raise
        def _raise_on_mutations(url):
            raise Exception("mutation error")

        detective._redirect_resolver.test_url_mutations = _raise_on_mutations

        report = detective.investigate("https://example.com/page", 404)

        assert isinstance(report, ForensicReport)
        assert any("mutation" in entry.lower() for entry in report.investigation.investigation_log)

    def test_archive_error_continues(self):
        """Exception in archive lookup doesn't stop the pipeline."""
        detective = _make_detective()
        detective._redirect_resolver = FakeRedirectResolver()
        archive = make_archive_miss()
        archive.get_latest_snapshot = lambda url: (_ for _ in ()).throw(Exception("archive error"))
        detective._archive_client = archive
        detective._url_heuristic = FakeURLHeuristic()
        detective._github_resolver = FakeGitHubResolver()

        report = detective.investigate("https://example.com/page", 404)

        assert isinstance(report, ForensicReport)
        assert any("archive" in entry.lower() for entry in report.investigation.investigation_log)

    def test_github_error_continues(self):
        """Exception in GitHub resolution doesn't stop the pipeline."""
        detective = _make_detective()
        detective._redirect_resolver = FakeRedirectResolver()
        detective._archive_client = make_archive_miss()
        detective._url_heuristic = FakeURLHeuristic()
        gh = FakeGitHubResolver(github_urls={"https://github.com/owner/repo"})
        gh._parse_github_url = lambda url: (_ for _ in ()).throw(Exception("github error"))
        detective._github_resolver = gh

        report = detective.investigate("https://github.com/owner/repo", 404)

        assert isinstance(report, ForensicReport)
        assert any("github" in entry.lower() for entry in report.investigation.investigation_log)
