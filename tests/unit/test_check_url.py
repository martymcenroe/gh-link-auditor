"""Unit tests for URL checking logic.

Updated to mock ``check_links.network_check_url`` after the refactor to
delegate to ``network.check_url`` (LLD #1).
"""

from unittest.mock import patch

from check_links import check_url
from gh_link_auditor.network import RequestResult


def _make_result(**overrides) -> RequestResult:
    """Helper to build a ``RequestResult`` with sensible defaults."""
    base: RequestResult = {
        "url": "https://example.com",
        "status": "ok",
        "status_code": 200,
        "method": "HEAD",
        "response_time_ms": 42,
        "retries": 0,
        "error": None,
    }
    base.update(overrides)
    return base


class TestCheckUrl:
    def test_ok_returns_ok_status(self):
        result_from_network = _make_result(status="ok", status_code=200, method="HEAD")
        with patch("check_links.network_check_url", return_value=result_from_network):
            result = check_url("https://example.com")
        assert "[  OK  ]" in result

    def test_404_returns_error(self):
        result_from_network = _make_result(
            status="error", status_code=404, method="HEAD", error="HTTP 404",
        )
        with patch("check_links.network_check_url", return_value=result_from_network):
            result = check_url("https://example.com")
        assert "[ ERROR ]" in result
        assert "404" in result

    def test_timeout_returns_timeout_after_retries(self):
        result_from_network = _make_result(
            status="timeout", status_code=None, method="HEAD", error="Request timed out",
        )
        with patch("check_links.network_check_url", return_value=result_from_network):
            result = check_url("https://example.com", retries=2)
        assert "[ TIMEOUT ]" in result

    def test_dns_failure_returns_failed(self):
        result_from_network = _make_result(
            status="failed", status_code=None, method="HEAD", error="DNS resolution failed",
        )
        with patch("check_links.network_check_url", return_value=result_from_network):
            result = check_url("https://nonexistent.invalid")
        assert "[ FAILED ]" in result
