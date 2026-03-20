"""Unit tests for link investigation orchestrator (LLD #20, §10.0).

TDD: Tests written BEFORE implementation.
Covers: LinkDetective.investigate(), data structures, cache, pipeline flow.
"""

import json
import urllib.error
from unittest.mock import patch

import pytest

from gh_link_auditor.link_detective import (
    CandidateReplacement,
    ForensicReport,
    Investigation,
    InvestigationMethod,
    LinkDetective,
    _check_wikipedia_suggestion,
    _extract_wiki_title,
    _is_wikipedia_url,
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


# ---------------------------------------------------------------------------
# Wikipedia URL detection
# ---------------------------------------------------------------------------


class TestIsWikipediaUrl:
    def test_en_wikipedia(self):
        assert _is_wikipedia_url("https://en.wikipedia.org/wiki/Python") is True

    def test_de_wikipedia(self):
        assert _is_wikipedia_url("https://de.wikipedia.org/wiki/Python") is True

    def test_simple_wikipedia(self):
        assert _is_wikipedia_url("https://simple.wikipedia.org/wiki/Cat") is True

    def test_not_wikipedia(self):
        assert _is_wikipedia_url("https://example.com/wiki/Page") is False

    def test_github_not_wikipedia(self):
        assert _is_wikipedia_url("https://github.com/owner/repo") is False


# ---------------------------------------------------------------------------
# Wikipedia title extraction
# ---------------------------------------------------------------------------


class TestExtractWikiTitle:
    def test_simple_title(self):
        assert _extract_wiki_title("https://en.wikipedia.org/wiki/Python") == "Python"

    def test_title_with_underscores(self):
        result = _extract_wiki_title("https://en.wikipedia.org/wiki/Python_(programming_language)")
        assert result == "Python_(programming_language)"

    def test_encoded_title(self):
        result = _extract_wiki_title("https://en.wikipedia.org/wiki/Caf%C3%A9")
        assert result == "Caf\u00e9"

    def test_trailing_slash_stripped(self):
        result = _extract_wiki_title("https://en.wikipedia.org/wiki/Python/")
        assert result == "Python"

    def test_fragment_stripped(self):
        result = _extract_wiki_title("https://en.wikipedia.org/wiki/Python#History")
        assert result == "Python"

    def test_no_wiki_prefix(self):
        assert _extract_wiki_title("https://en.wikipedia.org/w/index.php") is None

    def test_empty_title(self):
        assert _extract_wiki_title("https://en.wikipedia.org/wiki/") is None


# ---------------------------------------------------------------------------
# _check_wikipedia_suggestion unit tests
# ---------------------------------------------------------------------------


class TestCheckWikipediaSuggestion:
    def test_non_wikipedia_url_returns_none(self):
        result = _check_wikipedia_suggestion("https://example.com/wiki/Page")
        assert result is None

    def test_non_wiki_path_returns_none(self):
        result = _check_wikipedia_suggestion("https://en.wikipedia.org/w/index.php?title=Foo")
        assert result is None

    def test_redirect_found(self):
        """Wikipedia query API returns a redirect -> returns corrected URL."""
        api_response = {
            "query": {
                "redirects": [{"from": "Colour", "to": "Color"}],
                "pages": {"123": {"pageid": 123, "title": "Color"}},
            }
        }
        fake_resp = FakeURLResponse(json.dumps(api_response).encode("utf-8"))
        with patch(
            "gh_link_auditor.link_detective.urllib.request.urlopen",
            return_value=fake_resp,
        ):
            result = _check_wikipedia_suggestion("https://en.wikipedia.org/wiki/Colour")
        assert result == "https://en.wikipedia.org/wiki/Color"

    def test_page_exists_no_redirect(self):
        """Page exists but no redirect — returns the canonical URL."""
        api_response = {
            "query": {
                "pages": {"456": {"pageid": 456, "title": "Python (programming language)"}},
            }
        }
        fake_resp = FakeURLResponse(json.dumps(api_response).encode("utf-8"))
        with patch(
            "gh_link_auditor.link_detective.urllib.request.urlopen",
            return_value=fake_resp,
        ):
            result = _check_wikipedia_suggestion("https://en.wikipedia.org/wiki/Python_(programming_language)")
        assert result == "https://en.wikipedia.org/wiki/Python_(programming_language)"

    def test_page_missing_falls_through_to_opensearch(self):
        """Page missing in query API -> tries opensearch and finds suggestion."""
        query_response = {
            "query": {
                "pages": {"-1": {"title": "Pyhton", "missing": ""}},
            }
        }
        opensearch_response = [
            "Pyhton",
            ["Python (programming language)"],
            [""],
            ["https://en.wikipedia.org/wiki/Python_(programming_language)"],
        ]
        call_count = 0

        def fake_urlopen(req, timeout=10):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return FakeURLResponse(json.dumps(query_response).encode("utf-8"))
            return FakeURLResponse(json.dumps(opensearch_response).encode("utf-8"))

        with patch(
            "gh_link_auditor.link_detective.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            result = _check_wikipedia_suggestion("https://en.wikipedia.org/wiki/Pyhton")
        assert result == "https://en.wikipedia.org/wiki/Python_(programming_language)"

    def test_both_apis_fail_returns_none(self):
        """Both query and opensearch fail -> returns None."""
        with patch(
            "gh_link_auditor.link_detective.urllib.request.urlopen",
            side_effect=urllib.error.URLError("network error"),
        ):
            result = _check_wikipedia_suggestion("https://en.wikipedia.org/wiki/Nonexistent_Page_XYZ")
        assert result is None

    def test_opensearch_empty_returns_none(self):
        """Opensearch returns no suggestions -> returns None."""
        query_response = {
            "query": {
                "pages": {"-1": {"title": "Nonexistent", "missing": ""}},
            }
        }
        opensearch_response = ["Nonexistent", [], [], []]

        call_count = 0

        def fake_urlopen(req, timeout=10):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return FakeURLResponse(json.dumps(query_response).encode("utf-8"))
            return FakeURLResponse(json.dumps(opensearch_response).encode("utf-8"))

        with patch(
            "gh_link_auditor.link_detective.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            result = _check_wikipedia_suggestion("https://en.wikipedia.org/wiki/Nonexistent_Page_XYZ")
        assert result is None

    def test_redirect_chain_multiple_hops(self):
        """Multiple redirects -> uses the last one."""
        api_response = {
            "query": {
                "redirects": [
                    {"from": "A", "to": "B"},
                    {"from": "B", "to": "C"},
                ],
                "pages": {"789": {"pageid": 789, "title": "C"}},
            }
        }
        fake_resp = FakeURLResponse(json.dumps(api_response).encode("utf-8"))
        with patch(
            "gh_link_auditor.link_detective.urllib.request.urlopen",
            return_value=fake_resp,
        ):
            result = _check_wikipedia_suggestion("https://en.wikipedia.org/wiki/A")
        assert result == "https://en.wikipedia.org/wiki/C"

    def test_non_en_wikipedia(self):
        """Works for non-English Wikipedia domains."""
        api_response = {
            "query": {
                "redirects": [{"from": "Farbe", "to": "Farbe (Begriffserkl\u00e4rung)"}],
                "pages": {"100": {"pageid": 100, "title": "Farbe (Begriffserkl\u00e4rung)"}},
            }
        }
        fake_resp = FakeURLResponse(json.dumps(api_response).encode("utf-8"))
        with patch(
            "gh_link_auditor.link_detective.urllib.request.urlopen",
            return_value=fake_resp,
        ):
            result = _check_wikipedia_suggestion("https://de.wikipedia.org/wiki/Farbe")
        assert result is not None
        assert "de.wikipedia.org" in result

    def test_json_decode_error_returns_none(self):
        """Malformed JSON from API -> returns None gracefully."""
        fake_resp = FakeURLResponse(b"not json at all")
        with patch(
            "gh_link_auditor.link_detective.urllib.request.urlopen",
            return_value=fake_resp,
        ):
            result = _check_wikipedia_suggestion("https://en.wikipedia.org/wiki/Test")
        assert result is None

    def test_opensearch_same_url_skipped(self):
        """Opensearch suggesting the same dead URL -> returns None."""
        query_response = {
            "query": {
                "pages": {"-1": {"title": "Same_Page", "missing": ""}},
            }
        }
        opensearch_response = [
            "Same_Page",
            ["Same Page"],
            [""],
            ["https://en.wikipedia.org/wiki/Same_Page"],
        ]
        call_count = 0

        def fake_urlopen(req, timeout=10):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return FakeURLResponse(json.dumps(query_response).encode("utf-8"))
            return FakeURLResponse(json.dumps(opensearch_response).encode("utf-8"))

        with patch(
            "gh_link_auditor.link_detective.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            result = _check_wikipedia_suggestion("https://en.wikipedia.org/wiki/Same_Page")
        assert result is None


# ---------------------------------------------------------------------------
# Wikipedia suggestion in pipeline integration
# ---------------------------------------------------------------------------


class TestWikipediaSuggestionInPipeline:
    def test_wikipedia_suggestion_produces_candidate(self):
        """Wikipedia URL with redirect produces WIKIPEDIA_SUGGEST candidate."""
        detective = _make_detective()
        detective._redirect_resolver = FakeRedirectResolver(
            live_urls={"https://en.wikipedia.org/wiki/Color"},
        )
        detective._archive_client = make_archive_miss()
        detective._url_heuristic = FakeURLHeuristic()
        detective._github_resolver = FakeGitHubResolver()

        api_response = {
            "query": {
                "redirects": [{"from": "Colour", "to": "Color"}],
                "pages": {"123": {"pageid": 123, "title": "Color"}},
            }
        }
        fake_resp = FakeURLResponse(json.dumps(api_response).encode("utf-8"))
        with patch(
            "gh_link_auditor.link_detective.urllib.request.urlopen",
            return_value=fake_resp,
        ):
            report = detective.investigate("https://en.wikipedia.org/wiki/Colour", 404)

        candidates = report.investigation.candidate_replacements
        wiki_candidates = [c for c in candidates if c.method == InvestigationMethod.WIKIPEDIA_SUGGEST]
        assert len(wiki_candidates) == 1
        assert wiki_candidates[0].url == "https://en.wikipedia.org/wiki/Color"
        assert wiki_candidates[0].verified_live is True
        assert wiki_candidates[0].similarity_score == 0.95

    def test_wikipedia_suggestion_not_live_logged(self):
        """Wikipedia suggestion that isn't live gets logged but not added."""
        detective = _make_detective()
        detective._redirect_resolver = FakeRedirectResolver(
            live_urls=set(),  # nothing is live
        )
        detective._archive_client = make_archive_miss()
        detective._url_heuristic = FakeURLHeuristic()
        detective._github_resolver = FakeGitHubResolver()

        api_response = {
            "query": {
                "redirects": [{"from": "Old_Title", "to": "New_Title"}],
                "pages": {"100": {"pageid": 100, "title": "New_Title"}},
            }
        }
        fake_resp = FakeURLResponse(json.dumps(api_response).encode("utf-8"))
        with patch(
            "gh_link_auditor.link_detective.urllib.request.urlopen",
            return_value=fake_resp,
        ):
            report = detective.investigate("https://en.wikipedia.org/wiki/Old_Title", 404)

        wiki_candidates = [
            c for c in report.investigation.candidate_replacements if c.method == InvestigationMethod.WIKIPEDIA_SUGGEST
        ]
        assert len(wiki_candidates) == 0
        assert any("not live" in entry.lower() for entry in report.investigation.investigation_log)

    def test_non_wikipedia_url_skips_suggestion(self):
        """Non-Wikipedia URL does not trigger Wikipedia suggestion step."""
        detective = _make_detective()
        detective._redirect_resolver = FakeRedirectResolver()
        detective._archive_client = make_archive_miss()
        detective._url_heuristic = FakeURLHeuristic()
        detective._github_resolver = FakeGitHubResolver()

        report = detective.investigate("https://example.com/page", 404)

        assert not any("wikipedia" in entry.lower() for entry in report.investigation.investigation_log)

    def test_wikipedia_suggestion_error_continues_pipeline(self):
        """Exception in Wikipedia suggestion doesn't stop the pipeline."""
        detective = _make_detective()
        detective._redirect_resolver = FakeRedirectResolver()
        detective._archive_client = make_archive_miss()
        detective._url_heuristic = FakeURLHeuristic()
        detective._github_resolver = FakeGitHubResolver()

        with patch(
            "gh_link_auditor.link_detective._check_wikipedia_suggestion",
            side_effect=Exception("API timeout"),
        ):
            report = detective.investigate("https://en.wikipedia.org/wiki/Some_Article", 404)

        assert isinstance(report, ForensicReport)
        assert any(
            "wikipedia suggestion check failed" in entry.lower() for entry in report.investigation.investigation_log
        )

    def test_wikipedia_no_suggestion_logged(self):
        """No Wikipedia suggestion found is logged."""
        detective = _make_detective()
        detective._redirect_resolver = FakeRedirectResolver()
        detective._archive_client = make_archive_miss()
        detective._url_heuristic = FakeURLHeuristic()
        detective._github_resolver = FakeGitHubResolver()

        with patch(
            "gh_link_auditor.link_detective._check_wikipedia_suggestion",
            return_value=None,
        ):
            report = detective.investigate("https://en.wikipedia.org/wiki/Totally_Gone", 404)

        assert any("no wikipedia suggestion found" in entry.lower() for entry in report.investigation.investigation_log)


# ---------------------------------------------------------------------------
# InvestigationMethod enum includes WIKIPEDIA_SUGGEST
# ---------------------------------------------------------------------------


class TestWikipediaSuggestEnum:
    def test_wikipedia_suggest_value(self):
        assert InvestigationMethod.WIKIPEDIA_SUGGEST.value == "wikipedia_suggest"
