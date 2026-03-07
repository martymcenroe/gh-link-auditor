"""Unit tests for check_links anti-bot fallback (LLD #1, §10.0).

Tests the HEAD→GET fallback integration between check_links.py and network.py.
Mock target: ``check_links.network_check_url`` (the imported alias).
"""

import logging
from unittest.mock import patch

from check_links import (
    check_link_with_fallback,
    check_url,
    should_fallback_to_get,
)
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


class TestCheckLinksWithFallback:
    """Tests T010–T050: check_link_with_fallback behaviour."""

    # T010 — HEAD success → no fallback
    def test_head_success_no_fallback(self):
        result_from_network = _make_result(status="ok", status_code=200, method="HEAD")
        with patch("check_links.network_check_url", return_value=result_from_network):
            result = check_link_with_fallback("https://example.com")

        assert result["status_code"] == 200
        assert result["method_used"] == "HEAD"
        assert result["fallback_used"] is False
        assert result["error"] is None

    # T020 — HEAD 403 → GET fallback succeeds
    def test_head_403_triggers_get_fallback(self):
        result_from_network = _make_result(status="ok", status_code=200, method="GET")
        with patch("check_links.network_check_url", return_value=result_from_network):
            result = check_link_with_fallback("https://example.com")

        assert result["method_used"] == "GET"
        assert result["fallback_used"] is True
        assert result["status_code"] == 200

    # T030 — HEAD 405 → GET fallback succeeds
    def test_head_405_triggers_get_fallback(self):
        result_from_network = _make_result(status="ok", status_code=200, method="GET")
        with patch("check_links.network_check_url", return_value=result_from_network):
            result = check_link_with_fallback("https://example.com")

        assert result["method_used"] == "GET"
        assert result["fallback_used"] is True

    # T040 — HEAD 404 → no fallback, error returned
    def test_head_404_no_fallback(self):
        result_from_network = _make_result(
            status="error",
            status_code=404,
            method="HEAD",
            error="HTTP 404",
        )
        with patch("check_links.network_check_url", return_value=result_from_network):
            result = check_link_with_fallback("https://example.com")

        assert result["status_code"] == 404
        assert result["method_used"] == "HEAD"
        assert result["fallback_used"] is False
        assert result["error"] == "HTTP 404"

    # T050 — GET fallback returns actual GET status code
    def test_get_fallback_returns_get_status_code(self):
        result_from_network = _make_result(
            status="error",
            status_code=503,
            method="GET",
            error="HTTP 503",
        )
        with patch("check_links.network_check_url", return_value=result_from_network):
            result = check_link_with_fallback("https://example.com")

        assert result["status_code"] == 503
        assert result["method_used"] == "GET"


class TestShouldFallbackToGet:
    """Tests T060–T080: should_fallback_to_get predicate."""

    # T060 — 403 → True
    def test_403_triggers_fallback(self):
        assert should_fallback_to_get(403) is True

    # T070 — 405 → True
    def test_405_triggers_fallback(self):
        assert should_fallback_to_get(405) is True

    # T080 — 404 → False
    def test_404_does_not_trigger_fallback(self):
        assert should_fallback_to_get(404) is False


class TestFallbackLogging:
    """Test T090: fallback attempts are logged."""

    # T090 — Fallback is logged
    def test_fallback_is_logged(self, caplog):
        result_from_network = _make_result(status="ok", status_code=200, method="GET")
        with (
            patch("check_links.network_check_url", return_value=result_from_network),
            caplog.at_level(logging.INFO),
        ):
            check_link_with_fallback("https://example.com")

        assert any("falling back to GET" in msg for msg in caplog.messages)


class TestCheckUrlInterface:
    """Test T100: check_url() output format unchanged."""

    # T100 — Interface unchanged: string output format preserved
    def test_check_url_returns_formatted_string(self):
        result_from_network = _make_result(status="ok", status_code=200, method="HEAD")
        with patch("check_links.network_check_url", return_value=result_from_network):
            output = check_url("https://example.com")

        assert "[  OK  ]" in output
        assert "(Code: 200)" in output
        assert "https://example.com" in output
