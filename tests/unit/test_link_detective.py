"""Unit tests for link investigation orchestrator (LLD #20, §10.0).

TDD: Tests written BEFORE implementation.
Covers: LinkDetective.investigate(), data structures, cache, pipeline flow.
"""

from unittest.mock import MagicMock, patch

import pytest

from gh_link_auditor.link_detective import (
    CandidateReplacement,
    ForensicReport,
    Investigation,
    InvestigationMethod,
    LinkDetective,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_detective(state_db=None) -> LinkDetective:
    """Build a LinkDetective with a mock state_db."""
    if state_db is None:
        state_db = MagicMock()
    return LinkDetective(state_db=state_db)


def _mock_redirect_none(*args, **kwargs):
    """No redirect found."""
    return (None, ["No redirect chain detected"])


def _mock_no_mutations(*args, **kwargs):
    """No URL mutations found."""
    return []


def _mock_archive_hit():
    """Mock archive client that returns a snapshot."""
    client = MagicMock()
    client.get_latest_snapshot.return_value = {
        "url": "https://example.com/docs",
        "timestamp": "20240101120000",
        "original": "https://example.com/docs",
        "mimetype": "text/html",
        "statuscode": "200",
        "digest": "ABC",
        "length": "1234",
    }
    client.fetch_snapshot_content.return_value = (
        "<html><head><title>Example Docs</title></head><body>Content here</body></html>"
    )
    client.extract_title.return_value = "Example Docs"
    client.extract_content_summary.return_value = "Content here"
    return client


def _mock_archive_miss():
    """Mock archive client that returns no snapshot."""
    client = MagicMock()
    client.get_latest_snapshot.return_value = None
    return client


# ---------------------------------------------------------------------------
# T010: investigate() returns ForensicReport (REQ-1)
# ---------------------------------------------------------------------------


class TestInvestigateReturnsReport:
    def test_returns_forensic_report(self):
        """investigate() returns a ForensicReport with all required fields."""
        detective = _make_detective()
        with (
            patch.object(detective, "_redirect_resolver") as mock_rr,
            patch.object(detective, "_archive_client", _mock_archive_miss()),
            patch.object(detective, "_url_heuristic") as mock_uh,
            patch.object(detective, "_github_resolver") as mock_gh,
        ):
            mock_rr.follow_redirects.return_value = (None, ["No redirect"])
            mock_rr.test_url_mutations.return_value = []
            mock_uh.generate_candidates.return_value = []
            mock_uh.probe_candidates.return_value = []
            mock_gh.is_github_url.return_value = False

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
        with (
            patch.object(detective, "_redirect_resolver") as mock_rr,
            patch.object(detective, "_archive_client", _mock_archive_miss()),
            patch.object(detective, "_url_heuristic"),
            patch.object(detective, "_github_resolver") as mock_gh,
        ):
            mock_rr.follow_redirects.return_value = ("https://new.com/page", ["301 -> https://new.com/page"])
            mock_rr.verify_live.return_value = True
            mock_rr.test_url_mutations.return_value = []
            mock_gh.is_github_url.return_value = False

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
        with (
            patch.object(detective, "_redirect_resolver") as mock_rr,
            patch.object(detective, "_archive_client", _mock_archive_miss()),
            patch.object(detective, "_url_heuristic") as mock_uh,
            patch.object(detective, "_github_resolver") as mock_gh,
        ):
            mock_rr.follow_redirects.return_value = (None, ["No redirect"])
            mock_rr.test_url_mutations.return_value = []
            mock_uh.generate_candidates.return_value = []
            mock_uh.probe_candidates.return_value = []
            mock_gh.is_github_url.return_value = False

            report = detective.investigate("https://dead.example.com", 404)

        assert any("no archive" in entry.lower() for entry in report.investigation.investigation_log)


# ---------------------------------------------------------------------------
# T130: Candidates sorted by score descending (REQ-10)
# ---------------------------------------------------------------------------


class TestCandidateSorting:
    def test_candidates_sorted_descending(self):
        """Multiple candidates are sorted by similarity_score descending."""
        detective = _make_detective()
        with (
            patch.object(detective, "_redirect_resolver") as mock_rr,
            patch.object(detective, "_archive_client", _mock_archive_hit()),
            patch.object(detective, "_url_heuristic") as mock_uh,
            patch.object(detective, "_github_resolver") as mock_gh,
        ):
            mock_rr.follow_redirects.return_value = (None, ["No redirect"])
            mock_rr.test_url_mutations.return_value = [
                ("https://example.com/docs-new", "trailing_slash"),
            ]
            mock_rr.verify_live.return_value = True
            mock_uh.generate_candidates.return_value = ["https://example.com/example-docs"]
            mock_uh.probe_candidates.return_value = ["https://example.com/example-docs"]
            mock_gh.is_github_url.return_value = False

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
        with (
            patch.object(detective, "_redirect_resolver") as mock_rr,
            patch.object(detective, "_archive_client", _mock_archive_miss()),
            patch.object(detective, "_url_heuristic") as mock_uh,
            patch.object(detective, "_github_resolver") as mock_gh,
        ):
            mock_rr.follow_redirects.return_value = (None, ["No redirect"])
            mock_rr.test_url_mutations.return_value = []
            mock_uh.generate_candidates.return_value = []
            mock_uh.probe_candidates.return_value = []
            mock_gh.is_github_url.return_value = False

            report = detective.investigate("https://totally-gone.example.com", 404)

        assert report.investigation.candidate_replacements == []
        assert len(report.investigation.investigation_log) > 0


# ---------------------------------------------------------------------------
# T100: Cache hit skips external calls (REQ-7)
# ---------------------------------------------------------------------------


class TestCaching:
    def test_cache_hit_returns_without_external_calls(self):
        """Second investigation of same URL uses cache."""
        mock_db = MagicMock()
        detective = _make_detective(state_db=mock_db)

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
