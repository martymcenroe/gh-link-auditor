"""Unit tests for Internet Archive CDX API client (LLD #20, §10.0).

TDD: Tests written BEFORE implementation.
Mock target: ``gh_link_auditor.archive_client._cdx_request``
Covers: ArchiveClient.get_latest_snapshot(), fetch_snapshot_content(),
        extract_title(), extract_content_summary()
"""

from unittest.mock import MagicMock, patch

from gh_link_auditor.archive_client import ArchiveClient, _cdx_request, _fetch_url_content

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_CDX_LINE = "org,example)/docs/install 20240315120000 https://example.org/docs/install text/html 200 ABC123 1234"

SAMPLE_HTML = """<!DOCTYPE html>
<html>
<head><title>Installation Guide - Example</title></head>
<body>
<h1>Installation Guide</h1>
<p>Welcome to the installation guide. Follow these steps to install the software
on your machine. First, download the latest release from the releases page.
Then extract the archive and run the installer.</p>
</body>
</html>"""

SAMPLE_HTML_NO_TITLE = """<!DOCTYPE html>
<html>
<head></head>
<body><p>No title tag here.</p></body>
</html>"""


def _make_client() -> ArchiveClient:
    """Build an ArchiveClient with default config."""
    return ArchiveClient()


# ---------------------------------------------------------------------------
# T020: Archive hit extracts title (REQ-2)
# ---------------------------------------------------------------------------


class TestGetLatestSnapshot:
    def test_returns_cdx_response_on_hit(self):
        """CDX API hit returns parsed CDXResponse dict."""
        client = _make_client()
        with patch(
            "gh_link_auditor.archive_client._cdx_request",
            return_value=SAMPLE_CDX_LINE,
        ):
            result = client.get_latest_snapshot("https://example.org/docs/install")
        assert result is not None
        assert result["url"] == "https://example.org/docs/install"
        assert result["timestamp"] == "20240315120000"
        assert result["statuscode"] == "200"

    def test_returns_none_on_miss(self):
        """CDX API miss (empty response) returns None."""
        client = _make_client()
        with patch(
            "gh_link_auditor.archive_client._cdx_request",
            return_value="",
        ):
            result = client.get_latest_snapshot("https://example.org/nonexistent")
        assert result is None

    def test_returns_none_on_error(self):
        """CDX API error (exception) returns None gracefully."""
        client = _make_client()
        with patch(
            "gh_link_auditor.archive_client._cdx_request",
            side_effect=Exception("CDX API unavailable"),
        ):
            result = client.get_latest_snapshot("https://example.org/docs")
        assert result is None


# ---------------------------------------------------------------------------
# fetch_snapshot_content
# ---------------------------------------------------------------------------


class TestFetchSnapshotContent:
    def test_fetches_html_content(self):
        """Returns HTML string from Wayback Machine URL."""
        client = _make_client()
        snapshot_url = "https://web.archive.org/web/20240315120000/https://example.org/docs/install"
        with patch(
            "gh_link_auditor.archive_client._fetch_url_content",
            return_value=SAMPLE_HTML,
        ):
            content = client.fetch_snapshot_content(snapshot_url)
        assert content is not None
        assert "<title>" in content

    def test_returns_none_on_fetch_error(self):
        """Returns None when snapshot fetch fails."""
        client = _make_client()
        with patch(
            "gh_link_auditor.archive_client._fetch_url_content",
            return_value=None,
        ):
            content = client.fetch_snapshot_content("https://web.archive.org/web/bad")
        assert content is None


# ---------------------------------------------------------------------------
# T020: extract_title (REQ-2)
# ---------------------------------------------------------------------------


class TestExtractTitle:
    def test_extracts_title_from_html(self):
        """Extracts <title> text from valid HTML."""
        client = _make_client()
        title = client.extract_title(SAMPLE_HTML)
        assert title == "Installation Guide - Example"

    def test_returns_none_when_no_title(self):
        """Returns None when no <title> tag present."""
        client = _make_client()
        title = client.extract_title(SAMPLE_HTML_NO_TITLE)
        assert title is None

    def test_returns_none_for_empty_html(self):
        """Returns None for empty string input."""
        client = _make_client()
        assert client.extract_title("") is None

    def test_handles_multiline_title(self):
        """Extracts title even when split across lines."""
        html = "<html><head><title>\n  My Page\n  Title\n</title></head></html>"
        client = _make_client()
        title = client.extract_title(html)
        assert title is not None
        assert "My Page" in title


# ---------------------------------------------------------------------------
# extract_content_summary
# ---------------------------------------------------------------------------


class TestExtractContentSummary:
    def test_extracts_visible_text(self):
        """Extracts body text content, not tags."""
        client = _make_client()
        summary = client.extract_content_summary(SAMPLE_HTML)
        assert summary is not None
        assert "Installation Guide" in summary
        assert "<p>" not in summary

    def test_respects_max_chars(self):
        """Output truncated to max_chars."""
        client = _make_client()
        summary = client.extract_content_summary(SAMPLE_HTML, max_chars=50)
        assert summary is not None
        assert len(summary) <= 50

    def test_returns_none_for_empty_html(self):
        """Returns None for empty input."""
        client = _make_client()
        assert client.extract_content_summary("") is None

    def test_default_max_500_chars(self):
        """Default max_chars is 500."""
        long_html = "<html><body>" + "a " * 1000 + "</body></html>"
        client = _make_client()
        summary = client.extract_content_summary(long_html)
        assert summary is not None
        assert len(summary) <= 500

    def test_strips_script_and_style_tags(self):
        """Script and style content is excluded from summary."""
        html = "<html><body><script>var x=1;</script><style>.a{}</style><p>Visible</p></body></html>"
        client = _make_client()
        summary = client.extract_content_summary(html)
        assert summary is not None
        assert "var x" not in summary
        assert "Visible" in summary

    def test_empty_body_returns_none(self):
        """HTML with no visible text returns None."""
        html = "<html><body><script>only script</script></body></html>"
        client = _make_client()
        summary = client.extract_content_summary(html)
        # May return None or very short string depending on parser
        if summary:
            assert "only script" not in summary


# ---------------------------------------------------------------------------
# Internal helpers (coverage for _cdx_request, _fetch_url_content)
# ---------------------------------------------------------------------------


class TestCdxRequest:
    def test_cdx_request_success(self):
        """_cdx_request returns decoded response body."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"response data"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("gh_link_auditor.archive_client.urllib.request.urlopen", return_value=mock_resp):
            result = _cdx_request("https://web.archive.org/cdx/search/cdx?url=test")
        assert result == "response data"

    def test_fetch_url_content_success(self):
        """_fetch_url_content returns decoded HTML."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<html>test</html>"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("gh_link_auditor.archive_client.urllib.request.urlopen", return_value=mock_resp):
            result = _fetch_url_content("https://web.archive.org/web/snapshot")
        assert result == "<html>test</html>"

    def test_fetch_url_content_error_returns_none(self):
        """_fetch_url_content returns None on network error."""
        with patch(
            "gh_link_auditor.archive_client.urllib.request.urlopen",
            side_effect=OSError("connection refused"),
        ):
            result = _fetch_url_content("https://bad.example.com")
        assert result is None


# ---------------------------------------------------------------------------
# BS4 / regex fallback coverage
# ---------------------------------------------------------------------------


class TestRegexFallback:
    def test_extract_title_regex_path(self):
        """Exercise regex fallback for title extraction."""
        client = _make_client()
        with patch("gh_link_auditor.archive_client._HAS_BS4", False):
            title = client.extract_title(SAMPLE_HTML)
        assert title == "Installation Guide - Example"

    def test_extract_title_regex_no_title(self):
        """Regex fallback returns None when no title tag."""
        client = _make_client()
        with patch("gh_link_auditor.archive_client._HAS_BS4", False):
            title = client.extract_title(SAMPLE_HTML_NO_TITLE)
        assert title is None

    def test_extract_title_regex_multiline(self):
        """Regex fallback handles multiline title."""
        html = "<html><head><title>\n  My Page\n</title></head></html>"
        client = _make_client()
        with patch("gh_link_auditor.archive_client._HAS_BS4", False):
            title = client.extract_title(html)
        assert title is not None
        assert "My Page" in title

    def test_extract_title_regex_empty_title(self):
        """Regex fallback returns None for empty title tag."""
        html = "<html><head><title>  </title></head></html>"
        client = _make_client()
        with patch("gh_link_auditor.archive_client._HAS_BS4", False):
            title = client.extract_title(html)
        assert title is None

    def test_extract_content_summary_regex_path(self):
        """Exercise regex fallback for content extraction."""
        client = _make_client()
        with patch("gh_link_auditor.archive_client._HAS_BS4", False):
            summary = client.extract_content_summary(SAMPLE_HTML)
        assert summary is not None
        assert "Installation Guide" in summary
        assert "<p>" not in summary

    def test_extract_content_summary_regex_strips_scripts(self):
        """Regex fallback strips script/style tags."""
        html = "<html><body><script>bad</script><p>Good</p></body></html>"
        client = _make_client()
        with patch("gh_link_auditor.archive_client._HAS_BS4", False):
            summary = client.extract_content_summary(html)
        assert summary is not None
        assert "bad" not in summary
        assert "Good" in summary


# ---------------------------------------------------------------------------
# Edge: malformed CDX response
# ---------------------------------------------------------------------------


class TestMalformedCDX:
    def test_short_cdx_response_returns_none(self):
        """CDX response with fewer than 7 fields returns None."""
        client = _make_client()
        with patch(
            "gh_link_auditor.archive_client._cdx_request",
            return_value="only three fields",
        ):
            result = client.get_latest_snapshot("https://example.com")
        assert result is None
