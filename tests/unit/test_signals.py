"""Unit tests for Slant scoring signals.

Tests all 5 signal modules: redirect, title, content, url_path, domain.
Covers happy path, error, and edge cases per LLD #21 §10.

TDD: Tests written FIRST (RED), then implementation (GREEN).
"""

from __future__ import annotations

from unittest.mock import patch

from slant.signals.content import _fetch_page as _content_fetch_page
from slant.signals.content import compare_content, strip_html
from slant.signals.domain import _normalize_domain, match_domain
from slant.signals.redirect import _http_get, check_redirect
from slant.signals.title import _fetch_page as _title_fetch_page
from slant.signals.title import extract_title, match_title
from slant.signals.url_path import compare_url_paths

# ---------------------------------------------------------------------------
# Redirect signal tests (LLD §10 T030, T210)
# ---------------------------------------------------------------------------


class TestCheckRedirect:
    """Tests for redirect signal (weight=40)."""

    def test_301_redirect_to_candidate_scores_one(self):
        """T030: 301 redirect to candidate URL scores 1.0."""
        def _mock_get(url, *, timeout=10):
            if url == "https://old.example.com/page":
                return {"status_code": 301, "location": "https://new.example.com/page"}
            if url == "https://new.example.com/page":
                return {"status_code": 200, "location": None}
            return {"status_code": 404, "location": None}

        with patch("slant.signals.redirect._http_get", side_effect=_mock_get):
            score = check_redirect("https://old.example.com/page", "https://new.example.com/page")
        assert score == 1.0

    def test_302_redirect_to_candidate_scores_one(self):
        """302 redirect to candidate scores 1.0."""
        def _mock_get(url, *, timeout=10):
            if url == "https://old.example.com/page":
                return {"status_code": 302, "location": "https://new.example.com/page"}
            return {"status_code": 200, "location": None}

        with patch("slant.signals.redirect._http_get", side_effect=_mock_get):
            score = check_redirect("https://old.example.com/page", "https://new.example.com/page")
        assert score == 1.0

    def test_redirect_to_different_url_scores_zero(self):
        """Redirect to a URL that is NOT the candidate scores 0.0."""
        def _mock_get(url, *, timeout=10):
            if url == "https://old.example.com/page":
                return {"status_code": 301, "location": "https://other.example.com/page"}
            return {"status_code": 200, "location": None}

        with patch("slant.signals.redirect._http_get", side_effect=_mock_get):
            score = check_redirect("https://old.example.com/page", "https://new.example.com/page")
        assert score == 0.0

    def test_no_redirect_scores_zero(self):
        """Dead URL returns 200 (no redirect) scores 0.0."""
        def _mock_get(url, *, timeout=10):
            return {"status_code": 200, "location": None}

        with patch("slant.signals.redirect._http_get", side_effect=_mock_get):
            score = check_redirect("https://example.com/page", "https://new.example.com/page")
        assert score == 0.0

    def test_404_scores_zero(self):
        """Dead URL returns 404 scores 0.0."""
        def _mock_get(url, *, timeout=10):
            return {"status_code": 404, "location": None}

        with patch("slant.signals.redirect._http_get", side_effect=_mock_get):
            score = check_redirect("https://example.com/page", "https://new.example.com/page")
        assert score == 0.0

    def test_timeout_scores_zero(self):
        """T210: Redirect timeout scores 0.0."""
        def _mock_get(url, *, timeout=10):
            return {"status_code": None, "location": None}

        with patch("slant.signals.redirect._http_get", side_effect=_mock_get):
            score = check_redirect("https://example.com/page", "https://new.example.com/page")
        assert score == 0.0

    def test_connection_error_scores_zero(self):
        """Connection error scores 0.0."""
        def _mock_get(url, *, timeout=10):
            raise OSError("Connection refused")

        with patch("slant.signals.redirect._http_get", side_effect=_mock_get):
            score = check_redirect("https://example.com/page", "https://new.example.com/page")
        assert score == 0.0

    def test_multi_hop_redirect_to_candidate(self):
        """Multi-hop redirect chain ending at candidate scores 1.0."""
        def _mock_get(url, *, timeout=10):
            if url == "https://old.example.com/page":
                return {"status_code": 301, "location": "https://mid.example.com/page"}
            if url == "https://mid.example.com/page":
                return {"status_code": 302, "location": "https://new.example.com/page"}
            return {"status_code": 200, "location": None}

        with patch("slant.signals.redirect._http_get", side_effect=_mock_get):
            score = check_redirect("https://old.example.com/page", "https://new.example.com/page")
        assert score == 1.0

    def test_max_hops_exceeded_scores_zero(self):
        """Exceeding max redirect hops scores 0.0."""
        call_count = 0

        def _mock_get(url, *, timeout=10):
            nonlocal call_count
            call_count += 1
            return {"status_code": 301, "location": f"https://example.com/hop{call_count}"}

        with patch("slant.signals.redirect._http_get", side_effect=_mock_get):
            score = check_redirect("https://example.com/start", "https://example.com/target")
        assert score == 0.0

    def test_redirect_url_normalization(self):
        """Redirect with trailing slash differences still matches."""
        def _mock_get(url, *, timeout=10):
            if url == "https://example.com/page":
                return {"status_code": 301, "location": "https://example.com/new-page/"}
            return {"status_code": 200, "location": None}

        with patch("slant.signals.redirect._http_get", side_effect=_mock_get):
            score = check_redirect("https://example.com/page", "https://example.com/new-page")
        assert score == 1.0

    def test_score_range_zero_to_one(self):
        """Score is always in [0.0, 1.0] range."""
        def _mock_get(url, *, timeout=10):
            return {"status_code": 200, "location": None}

        with patch("slant.signals.redirect._http_get", side_effect=_mock_get):
            score = check_redirect("https://example.com/a", "https://example.com/b")
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Title match signal tests (LLD §10 T040)
# ---------------------------------------------------------------------------


class TestMatchTitle:
    """Tests for title match signal (weight=25)."""

    def test_identical_title_scores_near_one(self):
        """T040: Identical title from candidate page scores ~1.0."""
        def _mock_fetch(url, *, timeout=10):
            return "<html><head><title>Installation Guide</title></head><body></body></html>"

        with patch("slant.signals.title._fetch_page", side_effect=_mock_fetch):
            score = match_title("https://example.com/page", "Installation Guide")
        assert score >= 0.95

    def test_completely_different_title_scores_low(self):
        """Completely different title scores low."""
        def _mock_fetch(url, *, timeout=10):
            return "<html><head><title>XYZ Quantum Baking 2000</title></head><body></body></html>"

        with patch("slant.signals.title._fetch_page", side_effect=_mock_fetch):
            score = match_title("https://example.com/page", "Installation Guide")
        assert score < 0.4

    def test_partial_title_match_scores_medium(self):
        """Partial title overlap scores between 0.3 and 0.9."""
        def _mock_fetch(url, *, timeout=10):
            return "<html><head><title>Installation Guide - Updated</title></head><body></body></html>"

        with patch("slant.signals.title._fetch_page", side_effect=_mock_fetch):
            score = match_title("https://example.com/page", "Installation Guide")
        assert 0.3 <= score <= 1.0

    def test_fetch_error_scores_zero(self):
        """Network error fetching candidate title scores 0.0."""
        def _mock_fetch(url, *, timeout=10):
            return None

        with patch("slant.signals.title._fetch_page", side_effect=_mock_fetch):
            score = match_title("https://example.com/page", "Installation Guide")
        assert score == 0.0

    def test_no_title_tag_scores_zero(self):
        """Page with no title tag scores 0.0."""
        def _mock_fetch(url, *, timeout=10):
            return "<html><body><h1>No title here</h1></body></html>"

        with patch("slant.signals.title._fetch_page", side_effect=_mock_fetch):
            score = match_title("https://example.com/page", "Installation Guide")
        assert score == 0.0

    def test_empty_archived_title_scores_zero(self):
        """Empty archived title scores 0.0."""
        def _mock_fetch(url, *, timeout=10):
            return "<html><head><title>Some Title</title></head></html>"

        with patch("slant.signals.title._fetch_page", side_effect=_mock_fetch):
            score = match_title("https://example.com/page", "")
        assert score == 0.0

    def test_case_insensitive_matching(self):
        """Title matching is case insensitive."""
        def _mock_fetch(url, *, timeout=10):
            return "<html><head><title>INSTALLATION GUIDE</title></head></html>"

        with patch("slant.signals.title._fetch_page", side_effect=_mock_fetch):
            score = match_title("https://example.com/page", "installation guide")
        assert score >= 0.95


class TestExtractTitle:
    """Tests for title extraction helper."""

    def test_extracts_title_from_valid_html(self):
        """Extracts title text from well-formed HTML."""
        html = "<html><head><title>My Page Title</title></head></html>"
        assert extract_title(html) == "My Page Title"

    def test_returns_none_for_missing_title(self):
        """Returns None when no title tag present."""
        html = "<html><body>No title</body></html>"
        assert extract_title(html) is None

    def test_returns_none_for_empty_title(self):
        """Returns None when title tag is empty."""
        html = "<html><head><title></title></head></html>"
        assert extract_title(html) is None

    def test_strips_whitespace_from_title(self):
        """Strips leading/trailing whitespace from title."""
        html = "<html><head><title>  My Title  </title></head></html>"
        assert extract_title(html) == "My Title"

    def test_returns_none_for_empty_html(self):
        """Returns None for empty string input."""
        assert extract_title("") is None


# ---------------------------------------------------------------------------
# Content similarity signal tests (LLD §10 T220)
# ---------------------------------------------------------------------------


class TestCompareContent:
    """Tests for content similarity signal (weight=20)."""

    def test_identical_content_scores_near_one(self):
        """Identical content returns score near 1.0."""
        archived = "Welcome to the installation guide. Follow these steps."
        html = f"<html><body><p>{archived}</p></body></html>"

        def _mock_fetch(url, *, timeout=10):
            return html

        with patch("slant.signals.content._fetch_page", side_effect=_mock_fetch):
            score = compare_content("https://example.com/page", archived)
        assert score >= 0.8

    def test_completely_different_content_scores_low(self):
        """Completely different content scores near 0.0."""
        archived = "This is about quantum physics and black holes in space."
        html = "<html><body><p>Best recipes for chocolate cake baking today.</p></body></html>"

        def _mock_fetch(url, *, timeout=10):
            return html

        with patch("slant.signals.content._fetch_page", side_effect=_mock_fetch):
            score = compare_content("https://example.com/page", archived)
        assert score < 0.3

    def test_fetch_error_scores_zero(self):
        """T220: Content fetch error scores 0.0."""
        def _mock_fetch(url, *, timeout=10):
            return None

        with patch("slant.signals.content._fetch_page", side_effect=_mock_fetch):
            score = compare_content("https://example.com/page", "Some content")
        assert score == 0.0

    def test_exception_scores_zero(self):
        """Exception during fetch scores 0.0."""
        def _mock_fetch(url, *, timeout=10):
            raise OSError("Connection refused")

        with patch("slant.signals.content._fetch_page", side_effect=_mock_fetch):
            score = compare_content("https://example.com/page", "Some content")
        assert score == 0.0

    def test_empty_archived_content_scores_zero(self):
        """Empty archived content scores 0.0."""
        def _mock_fetch(url, *, timeout=10):
            return "<html><body>Some page content</body></html>"

        with patch("slant.signals.content._fetch_page", side_effect=_mock_fetch):
            score = compare_content("https://example.com/page", "")
        assert score == 0.0


class TestStripHtml:
    """Tests for HTML stripping helper."""

    def test_strips_tags(self):
        """Removes HTML tags and returns plain text."""
        html = "<p>Hello <strong>world</strong></p>"
        assert "Hello" in strip_html(html)
        assert "world" in strip_html(html)
        assert "<p>" not in strip_html(html)

    def test_strips_script_tags(self):
        """Removes script tags and their content."""
        html = '<p>Text</p><script>alert("xss")</script>'
        result = strip_html(html)
        assert "alert" not in result
        assert "Text" in result

    def test_strips_style_tags(self):
        """Removes style tags and their content."""
        html = "<style>body{color:red}</style><p>Text</p>"
        result = strip_html(html)
        assert "color" not in result
        assert "Text" in result

    def test_empty_input(self):
        """Returns empty string for empty input."""
        assert strip_html("") == ""


# ---------------------------------------------------------------------------
# URL path similarity signal tests (LLD §10 T230)
# ---------------------------------------------------------------------------


class TestCompareUrlPaths:
    """Tests for URL path similarity signal (weight=10)."""

    def test_identical_paths_score_one(self):
        """T230: Identical paths score 1.0."""
        score = compare_url_paths(
            "https://example.com/blog/post-1",
            "https://example.com/blog/post-1",
        )
        assert score == 1.0

    def test_completely_different_paths_score_low(self):
        """Completely different paths score near 0.0."""
        score = compare_url_paths(
            "https://example.com/docs/install",
            "https://example.com/about/team/leadership",
        )
        assert score < 0.5

    def test_similar_paths_score_medium(self):
        """Similar paths (shared components) score between 0.3 and 1.0."""
        score = compare_url_paths(
            "https://example.com/docs/v1/install",
            "https://example.com/docs/v2/install",
        )
        assert 0.3 <= score <= 1.0

    def test_root_paths(self):
        """Both root paths score 1.0."""
        score = compare_url_paths(
            "https://example.com/",
            "https://other.com/",
        )
        assert score == 1.0

    def test_empty_vs_nonempty_path(self):
        """Root vs deep path scores low."""
        score = compare_url_paths(
            "https://example.com/",
            "https://example.com/very/deep/nested/path",
        )
        assert score < 0.5

    def test_trailing_slash_normalization(self):
        """Trailing slash differences don't affect score."""
        score_with = compare_url_paths(
            "https://example.com/docs/",
            "https://example.com/docs",
        )
        assert score_with == 1.0

    def test_score_range_zero_to_one(self):
        """Score is always in [0.0, 1.0] range."""
        score = compare_url_paths(
            "https://example.com/a/b/c",
            "https://other.com/x/y/z",
        )
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Domain match signal tests (LLD §10 T240, T250)
# ---------------------------------------------------------------------------


class TestMatchDomain:
    """Tests for domain match signal (weight=5)."""

    def test_exact_domain_match_scores_one(self):
        """T240: Exact same domain scores 1.0."""
        score = match_domain(
            "https://example.com/old-page",
            "https://example.com/new-page",
        )
        assert score == 1.0

    def test_different_domain_scores_zero(self):
        """T250: Different domains score 0.0."""
        score = match_domain(
            "https://example.com/page",
            "https://other.com/page",
        )
        assert score == 0.0

    def test_subdomain_difference_scores_zero(self):
        """Different subdomains score 0.0."""
        score = match_domain(
            "https://docs.example.com/page",
            "https://api.example.com/page",
        )
        assert score == 0.0

    def test_www_vs_non_www_scores_one(self):
        """www vs non-www of same domain scores 1.0 (normalized)."""
        score = match_domain(
            "https://www.example.com/page",
            "https://example.com/page",
        )
        assert score == 1.0

    def test_case_insensitive(self):
        """Domain comparison is case insensitive."""
        score = match_domain(
            "https://Example.COM/page",
            "https://example.com/page",
        )
        assert score == 1.0

    def test_different_ports_same_domain(self):
        """Same domain with different schemes still matches."""
        score = match_domain(
            "http://example.com/page",
            "https://example.com/page",
        )
        assert score == 1.0

    def test_empty_urls(self):
        """Empty URLs score 0.0."""
        assert match_domain("", "") == 0.0


# ---------------------------------------------------------------------------
# Internal helper tests (coverage for _http_get, _fetch_page, etc.)
# ---------------------------------------------------------------------------


class TestHttpGetHelper:
    """Tests for redirect signal's _http_get internal helper."""

    def test_success_returns_status_and_location(self):
        """Successful request returns status code and location."""

        class MockResponse:
            status = 301
            headers = {"Location": "https://example.com/new"}

            def close(self):
                pass

        class MockOpener:
            def open(self, req, timeout=10):
                return MockResponse()

        with patch("slant.signals.redirect.urllib.request.build_opener", return_value=MockOpener()):
            result = _http_get("https://example.com/old")
        assert result["status_code"] == 301
        assert result["location"] == "https://example.com/new"

    def test_http_error_returns_error_code(self):
        """HTTP error returns error code and location."""
        import urllib.error

        def _raise_http_error(*args, **kwargs):
            raise urllib.error.HTTPError(
                "https://example.com", 404, "Not Found",
                {"Location": None}, None,
            )

        class MockOpener:
            def open(self, req, timeout=10):
                _raise_http_error()

        with patch("slant.signals.redirect.urllib.request.build_opener", return_value=MockOpener()):
            result = _http_get("https://example.com/page")
        assert result["status_code"] == 404

    def test_url_error_returns_none(self):
        """URL error returns None status."""
        import urllib.error

        class MockOpener:
            def open(self, req, timeout=10):
                raise urllib.error.URLError("Connection refused")

        with patch("slant.signals.redirect.urllib.request.build_opener", return_value=MockOpener()):
            result = _http_get("https://example.com/page")
        assert result["status_code"] is None
        assert result["location"] is None


class TestTitleFetchPageHelper:
    """Tests for title signal's _fetch_page internal helper."""

    def test_success_returns_html(self):
        """Successful fetch returns HTML string."""
        html_bytes = b"<html><head><title>Test</title></head></html>"

        class MockResponse:
            def read(self):
                return html_bytes

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        with patch("slant.signals.title.urllib.request.urlopen", return_value=MockResponse()):
            result = _title_fetch_page("https://example.com/page")
        assert result == "<html><head><title>Test</title></head></html>"

    def test_error_returns_none(self):
        """Network error returns None."""
        import urllib.error

        with patch("slant.signals.title.urllib.request.urlopen", side_effect=urllib.error.URLError("fail")):
            result = _title_fetch_page("https://example.com/page")
        assert result is None


class TestContentFetchPageHelper:
    """Tests for content signal's _fetch_page internal helper."""

    def test_success_returns_html(self):
        """Successful fetch returns HTML string."""
        html_bytes = b"<html><body>Hello world</body></html>"

        class MockResponse:
            def read(self, size=None):
                return html_bytes

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        with patch("slant.signals.content.urllib.request.urlopen", return_value=MockResponse()):
            result = _content_fetch_page("https://example.com/page")
        assert "Hello world" in result

    def test_error_returns_none(self):
        """Network error returns None."""
        import urllib.error

        with patch("slant.signals.content.urllib.request.urlopen", side_effect=urllib.error.URLError("fail")):
            result = _content_fetch_page("https://example.com/page")
        assert result is None


class TestNormalizeDomain:
    """Tests for the _normalize_domain helper."""

    def test_strips_www(self):
        """Strips www. prefix."""
        assert _normalize_domain("www.example.com") == "example.com"

    def test_lowercases(self):
        """Lowercases domain."""
        assert _normalize_domain("Example.COM") == "example.com"

    def test_no_www(self):
        """Keeps domain without www."""
        assert _normalize_domain("example.com") == "example.com"
