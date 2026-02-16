"""Unit tests for URL checking logic."""

import urllib.error
from unittest.mock import MagicMock, patch

from check_links import check_url


class TestCheckUrl:
    def test_ok_returns_ok_status(self):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("check_links.urllib.request.urlopen", return_value=mock_response):
            result = check_url("https://example.com")
        assert "[  OK  ]" in result

    def test_404_returns_error(self):
        error = urllib.error.HTTPError(url="https://example.com", code=404, msg="Not Found", hdrs=None, fp=None)
        with patch("check_links.urllib.request.urlopen", side_effect=error):
            result = check_url("https://example.com")
        assert "[ ERROR ]" in result
        assert "404" in result

    def test_timeout_returns_timeout_after_retries(self):
        error = urllib.error.URLError(reason="timed out")
        with patch("check_links.urllib.request.urlopen", side_effect=error):
            with patch("check_links.time.sleep"):
                result = check_url("https://example.com", retries=2)
        assert "[ TIMEOUT ]" in result

    def test_dns_failure_returns_failed(self):
        error = urllib.error.URLError(reason="Name or service not known")
        with patch("check_links.urllib.request.urlopen", side_effect=error):
            result = check_url("https://nonexistent.invalid")
        assert "[ FAILED ]" in result
