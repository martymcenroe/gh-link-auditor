"""Unit tests for gh_link_auditor.network module.

Tests cover all scenarios from LLD-009 §10.1 using mocked HTTP responses.
No external network calls are made during testing.
"""

from __future__ import annotations

import http.client
import socket
import ssl
import urllib.error
import urllib.request
from unittest import mock

import pytest

from gh_link_auditor.network import (
    BackoffConfig,
    RequestConfig,
    _create_ssl_context,
    _make_request,
    _parse_retry_after,
    calculate_backoff_delay,
    check_url,
    create_backoff_config,
    create_request_config,
    should_retry,
)
from tests.fakes.http import FakeURLResponse

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def default_request_config() -> RequestConfig:
    """Provide a default request configuration for tests."""
    return create_request_config()


@pytest.fixture
def default_backoff_config() -> BackoffConfig:
    """Provide a default backoff configuration for tests."""
    return create_backoff_config()


@pytest.fixture
def no_retry_backoff_config() -> BackoffConfig:
    """Provide a backoff config with zero retries for single-attempt tests."""
    return create_backoff_config(max_retries=0)


def _mock_urlopen_response(status: int = 200, headers: dict | None = None):
    """Create a fake response object for urllib.request.urlopen."""
    return FakeURLResponse(data=b"", status=status, headers=headers or {})


# ---------------------------------------------------------------------------
# T010 / 010: Successful HEAD request returns structured result (REQ-1)
# ---------------------------------------------------------------------------


class TestCheckUrlSuccessHead:
    """T010 / 010: Returns ok status for 200 response."""

    def test_check_url_success_head(self, no_retry_backoff_config):
        """Successful HEAD returns status='ok', status_code=200."""
        mock_resp = _mock_urlopen_response(status=200)
        with mock.patch("gh_link_auditor.network.urllib.request.urlopen", return_value=mock_resp):
            result = check_url(
                "https://example.com",
                backoff_config=no_retry_backoff_config,
            )

        assert result["status"] == "ok"
        assert result["status_code"] == 200
        assert result["method"] == "HEAD"
        assert result["retries"] == 0
        assert result["error"] is None
        assert result["url"] == "https://example.com"
        assert isinstance(result["response_time_ms"], int)


# ---------------------------------------------------------------------------
# T020 / 020: Redirect response treated as success (REQ-1)
# ---------------------------------------------------------------------------


class TestCheckUrlRedirect:
    """T020 / 020: Returns ok status for 301/302."""

    @pytest.mark.parametrize("status_code", [301, 302])
    def test_check_url_redirect(self, status_code, no_retry_backoff_config):
        """Redirect responses (301, 302) are treated as ok."""
        mock_resp = _mock_urlopen_response(status=status_code)
        with mock.patch("gh_link_auditor.network.urllib.request.urlopen", return_value=mock_resp):
            result = check_url(
                "https://example.com/old",
                backoff_config=no_retry_backoff_config,
            )

        assert result["status"] == "ok"
        assert result["status_code"] == status_code


# ---------------------------------------------------------------------------
# T030 / 030: Not found response returns error immediately (REQ-6)
# ---------------------------------------------------------------------------


class TestCheckUrlNotFound:
    """T030 / 030: Returns error status for 404 with no retry."""

    def test_check_url_not_found(self):
        """404 returns error immediately without retry."""
        http_error = urllib.error.HTTPError(
            "https://example.com/missing",
            404,
            "Not Found",
            {},
            None,
        )
        with mock.patch("gh_link_auditor.network.urllib.request.urlopen", side_effect=http_error):
            result = check_url("https://example.com/missing")

        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert result["retries"] == 0
        assert result["error"] is not None


# ---------------------------------------------------------------------------
# T040 / 040: Server error response categorized correctly (REQ-6)
# ---------------------------------------------------------------------------


class TestCheckUrlServerError:
    """T040 / 040: Returns error status for 500."""

    def test_check_url_server_error(self):
        """500 returns error status."""
        http_error = urllib.error.HTTPError(
            "https://example.com/error",
            500,
            "Internal Server Error",
            {},
            None,
        )
        with mock.patch("gh_link_auditor.network.urllib.request.urlopen", side_effect=http_error):
            result = check_url(
                "https://example.com/error",
                backoff_config=create_backoff_config(max_retries=0),
            )

        assert result["status"] == "error"
        assert result["status_code"] == 500


# ---------------------------------------------------------------------------
# T050 / 050: HEAD blocked 405 triggers GET fallback (REQ-3)
# ---------------------------------------------------------------------------


class TestHeadToGetFallback405:
    """T050 / 050: Falls back to GET on 405, then succeeds."""

    def test_head_to_get_fallback_405(self, no_retry_backoff_config):
        """405 on HEAD triggers GET fallback; returns ok on GET 200."""
        http_error_405 = urllib.error.HTTPError(
            "https://example.com",
            405,
            "Method Not Allowed",
            {},
            None,
        )
        mock_resp_200 = _mock_urlopen_response(status=200)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # Inspect the request method
            request_obj = args[0]
            if request_obj.get_method() == "HEAD":
                raise http_error_405
            return mock_resp_200

        with mock.patch("gh_link_auditor.network.urllib.request.urlopen", side_effect=side_effect):
            result = check_url(
                "https://example.com",
                backoff_config=no_retry_backoff_config,
            )

        assert result["status"] == "ok"
        assert result["method"] == "GET"
        assert result["retries"] == 0  # Fallback is not counted as retry


# ---------------------------------------------------------------------------
# T060 / 060: HEAD blocked 403 triggers GET fallback (REQ-3)
# ---------------------------------------------------------------------------


class TestHeadToGetFallback403:
    """T060 / 060: Falls back to GET on 403, then succeeds."""

    def test_head_to_get_fallback_403(self, no_retry_backoff_config):
        """403 on HEAD triggers GET fallback; returns ok on GET 200."""
        http_error_403 = urllib.error.HTTPError(
            "https://example.com",
            403,
            "Forbidden",
            {},
            None,
        )
        mock_resp_200 = _mock_urlopen_response(status=200)

        def side_effect(*args, **kwargs):
            request_obj = args[0]
            if request_obj.get_method() == "HEAD":
                raise http_error_403
            return mock_resp_200

        with mock.patch("gh_link_auditor.network.urllib.request.urlopen", side_effect=side_effect):
            result = check_url(
                "https://example.com",
                backoff_config=no_retry_backoff_config,
            )

        assert result["status"] == "ok"
        assert result["method"] == "GET"
        assert result["retries"] == 0


# ---------------------------------------------------------------------------
# T070 / 070: Rate limited 429 triggers exponential backoff retry (REQ-2)
# ---------------------------------------------------------------------------


class TestRetryOn429:
    """T070 / 070: Retries with backoff on 429, eventually succeeds."""

    def test_retry_on_429(self):
        """429 twice then 200 → ok with retries=2."""
        headers_429 = {}  # Empty headers dict (no Retry-After)

        http_error_429 = urllib.error.HTTPError(
            "https://example.com",
            429,
            "Too Many Requests",
            headers_429,
            None,
        )
        mock_resp_200 = _mock_urlopen_response(status=200)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise http_error_429
            return mock_resp_200

        backoff = create_backoff_config(base_delay=0.01, max_delay=0.1, max_retries=2, jitter_range=0.0)

        with mock.patch("gh_link_auditor.network.urllib.request.urlopen", side_effect=side_effect):
            with mock.patch("gh_link_auditor.network.time.sleep"):
                result = check_url(
                    "https://example.com",
                    backoff_config=backoff,
                )

        assert result["status"] == "ok"
        assert result["retries"] == 2


# ---------------------------------------------------------------------------
# T080 / 080: Retry-After header honored on 429 response (REQ-4)
# ---------------------------------------------------------------------------


class TestRetryRespectsRetryAfter:
    """T080 / 080: Uses Retry-After header value."""

    def test_retry_respects_retry_after(self):
        """429 with Retry-After: 5 → delay ≥ 5 seconds."""
        headers_429 = {"Retry-After": "5"}

        http_error_429 = urllib.error.HTTPError(
            "https://example.com",
            429,
            "Too Many Requests",
            headers_429,
            None,
        )
        mock_resp_200 = _mock_urlopen_response(status=200)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise http_error_429
            return mock_resp_200

        backoff = create_backoff_config(base_delay=0.01, max_delay=30.0, max_retries=2, jitter_range=0.0)

        with mock.patch("gh_link_auditor.network.urllib.request.urlopen", side_effect=side_effect):
            with mock.patch("gh_link_auditor.network.time.sleep") as mock_sleep:
                result = check_url(
                    "https://example.com",
                    backoff_config=backoff,
                )

        assert result["status"] == "ok"
        # The sleep call should have been called with delay >= 5
        mock_sleep.assert_called_once()
        actual_delay = mock_sleep.call_args[0][0]
        assert actual_delay >= 5.0, f"Expected delay >= 5.0, got {actual_delay}"


# ---------------------------------------------------------------------------
# T090 / 090: Request timeout returns timeout status (REQ-6)
# ---------------------------------------------------------------------------


class TestTimeoutHandling:
    """T090 / 090: Returns timeout status."""

    def test_timeout_handling(self):
        """Simulated timeout returns status='timeout'."""
        timeout_error = urllib.error.URLError(socket.timeout("timed out"))

        with mock.patch("gh_link_auditor.network.urllib.request.urlopen", side_effect=timeout_error):
            with mock.patch("gh_link_auditor.network.time.sleep"):
                result = check_url(
                    "https://example.com/slow",
                    backoff_config=create_backoff_config(max_retries=0),
                )

        assert result["status"] == "timeout"
        assert result["status_code"] is None
        assert result["error"] is not None


# ---------------------------------------------------------------------------
# T100 / 100: Connection reset returns disconnected status (REQ-6)
# ---------------------------------------------------------------------------


class TestConnectionReset:
    """T100 / 100: Returns disconnected status."""

    def test_connection_reset(self):
        """RemoteDisconnected returns status='disconnected'."""
        with mock.patch(
            "gh_link_auditor.network.urllib.request.urlopen",
            side_effect=http.client.RemoteDisconnected("Remote end closed connection"),
        ):
            with mock.patch("gh_link_auditor.network.time.sleep"):
                result = check_url(
                    "https://example.com/reset",
                    backoff_config=create_backoff_config(max_retries=0),
                )

        assert result["status"] == "disconnected"
        assert result["status_code"] is None
        assert result["error"] is not None


# ---------------------------------------------------------------------------
# T110 / 110: DNS failure returns failed status without retry (REQ-6)
# ---------------------------------------------------------------------------


class TestDnsFailure:
    """T110 / 110: Returns failed status, no retry."""

    def test_dns_failure(self):
        """DNS failure returns status='failed', retries=0."""
        dns_error = urllib.error.URLError(
            OSError("[Errno 11001] getaddrinfo failed"),
        )

        with mock.patch("gh_link_auditor.network.urllib.request.urlopen", side_effect=dns_error):
            result = check_url("https://nonexistent.invalid")

        assert result["status"] == "failed"
        assert result["retries"] == 0
        assert result["status_code"] is None


# ---------------------------------------------------------------------------
# T120 / 120: Backoff calculation uses exponential with jitter (REQ-2)
# ---------------------------------------------------------------------------


class TestBackoffCalculation:
    """T120 / 120: Correct exponential + jitter."""

    def test_backoff_calculation_attempt_0(self):
        """Attempt 0: delay = base_delay * 2^0 + jitter = 1.0 + [0, 1.0]."""
        config = create_backoff_config(base_delay=1.0, max_delay=30.0, jitter_range=1.0)
        # Fix random seed for determinism
        with mock.patch("gh_link_auditor.network.random.uniform", return_value=0.5):
            delay = calculate_backoff_delay(0, config)
        assert delay == pytest.approx(1.5)  # 1.0 * 1 + 0.5

    def test_backoff_calculation_attempt_2(self):
        """Attempt 2: delay = 1.0 * 2^2 + jitter = 4.0 + [0, 1.0]."""
        config = create_backoff_config(base_delay=1.0, max_delay=30.0, jitter_range=1.0)
        with mock.patch("gh_link_auditor.network.random.uniform", return_value=0.5):
            delay = calculate_backoff_delay(2, config)
        assert delay == pytest.approx(4.5)  # 1.0 * 4 + 0.5

    def test_backoff_calculation_range(self):
        """Attempt 2 with default jitter range gives delay in [4.0, 5.0]."""
        config = create_backoff_config(base_delay=1.0, max_delay=30.0, jitter_range=1.0)
        # Run multiple times to check bounds
        delays = set()
        for _ in range(100):
            delay = calculate_backoff_delay(2, config)
            delays.add(delay)
            assert 4.0 <= delay <= 5.0, f"Delay {delay} outside expected range [4.0, 5.0]"

    def test_backoff_respects_max_delay(self):
        """Delay never exceeds max_delay."""
        config = create_backoff_config(base_delay=10.0, max_delay=5.0, jitter_range=1.0)
        delay = calculate_backoff_delay(10, config)
        assert delay <= 5.0

    def test_backoff_with_retry_after(self):
        """Retry-After takes precedence when larger than calculated delay."""
        config = create_backoff_config(base_delay=1.0, max_delay=30.0, jitter_range=0.0)
        delay = calculate_backoff_delay(0, config, retry_after=10)
        assert delay == 10.0  # retry_after > calculated (1.0)

    def test_backoff_retry_after_capped_by_max(self):
        """Retry-After is still capped by max_delay."""
        config = create_backoff_config(base_delay=1.0, max_delay=5.0, jitter_range=0.0)
        delay = calculate_backoff_delay(0, config, retry_after=100)
        assert delay == 5.0


# ---------------------------------------------------------------------------
# T130 / 130: Max retries limit enforced (REQ-2)
# ---------------------------------------------------------------------------


class TestMaxRetriesHonored:
    """T130 / 130: Stops after max_retries."""

    def test_max_retries_honored(self):
        """Always 429 → stops at max_retries=2, returns error."""
        headers_429 = {}  # Empty headers dict (no Retry-After)

        http_error_429 = urllib.error.HTTPError(
            "https://example.com",
            429,
            "Too Many Requests",
            headers_429,
            None,
        )

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise http_error_429

        backoff = create_backoff_config(base_delay=0.01, max_delay=0.1, max_retries=2, jitter_range=0.0)

        with mock.patch("gh_link_auditor.network.urllib.request.urlopen", side_effect=side_effect):
            with mock.patch("gh_link_auditor.network.time.sleep"):
                result = check_url(
                    "https://example.com",
                    backoff_config=backoff,
                )

        assert result["status"] == "error"
        assert result["status_code"] == 429
        assert result["retries"] == 2
        # 1 initial + 2 retries = 3 total calls
        assert call_count == 3


# ---------------------------------------------------------------------------
# T140 / 140: Custom User-Agent configuration applied (REQ-5)
# ---------------------------------------------------------------------------


class TestCustomUserAgent:
    """T140 / 140: Sends configured User-Agent."""

    def test_custom_user_agent(self):
        """Custom UA string is sent in the request headers."""
        captured_requests = []

        def capturing_urlopen(req, **kwargs):
            captured_requests.append(req)
            resp = _mock_urlopen_response(status=200)
            return resp

        custom_ua = "MyCustomBot/1.0"
        config = create_request_config(user_agent=custom_ua)

        with mock.patch("gh_link_auditor.network.urllib.request.urlopen", side_effect=capturing_urlopen):
            check_url("https://example.com", request_config=config)

        assert len(captured_requests) >= 1
        sent_ua = captured_requests[0].get_header("User-agent")
        assert sent_ua == custom_ua


# ---------------------------------------------------------------------------
# T150 / 150: SSL verification configuration respected (REQ-5)
# ---------------------------------------------------------------------------


class TestSslVerificationConfigurable:
    """T150 / 150: Respects verify_ssl setting."""

    def test_ssl_verify_true_default(self):
        """Default config creates context with verification enabled."""
        ctx = _create_ssl_context(verify=True)
        assert ctx.check_hostname is True
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_ssl_verify_false(self):
        """verify_ssl=False creates context with verification disabled."""
        ctx = _create_ssl_context(verify=False)
        assert ctx.check_hostname is False
        assert ctx.verify_mode == ssl.CERT_NONE

    def test_ssl_config_passed_to_request(self):
        """verify_ssl=False is passed through to _make_request."""
        config = create_request_config(verify_ssl=False)

        with mock.patch("gh_link_auditor.network._create_ssl_context") as mock_ctx:
            mock_ctx.return_value = ssl.create_default_context()
            mock_ctx.return_value.check_hostname = False
            mock_ctx.return_value.verify_mode = ssl.CERT_NONE

            mock_resp = _mock_urlopen_response(status=200)
            with mock.patch("gh_link_auditor.network.urllib.request.urlopen", return_value=mock_resp):
                check_url("https://example.com", request_config=config)

            mock_ctx.assert_called_with(False)


# ---------------------------------------------------------------------------
# 160: Module uses only stdlib dependencies (REQ-7)
# ---------------------------------------------------------------------------


class TestStdlibOnly:
    """160: No external imports in the network module."""

    def test_no_external_dependencies(self):
        """Network module imports only stdlib packages."""
        # Known external packages that should NOT be imported
        banned_packages = {"requests", "urllib3", "httpx", "aiohttp", "httplib2"}

        # Import the module fresh and check
        import gh_link_auditor.network as net_module

        # Get all modules that the network module has imported
        # by checking what's referenced in its namespace
        module_imports = set()
        for attr_name in dir(net_module):
            attr = getattr(net_module, attr_name)
            if hasattr(attr, "__module__"):
                top_package = attr.__module__.split(".")[0]
                module_imports.add(top_package)

        violations = module_imports & banned_packages
        assert not violations, f"Banned packages imported: {violations}"


# ---------------------------------------------------------------------------
# Additional tests for _parse_retry_after
# ---------------------------------------------------------------------------


class TestParseRetryAfter:
    """Tests for the _parse_retry_after helper."""

    def test_parse_integer_seconds(self):
        """Integer string is parsed to int."""
        assert _parse_retry_after("5") == 5

    def test_parse_zero(self):
        """Zero is valid."""
        assert _parse_retry_after("0") == 0

    def test_parse_none(self):
        """None returns None."""
        assert _parse_retry_after(None) is None

    def test_parse_invalid(self):
        """Non-parseable string returns None."""
        assert _parse_retry_after("not-a-number-or-date") is None

    def test_parse_http_date(self):
        """HTTP-date format is parsed relative to current time."""
        # Use a date far in the future to get a positive delay
        future_date = "Wed, 01 Jan 2099 00:00:00 GMT"
        result = _parse_retry_after(future_date)
        assert result is not None
        assert result > 0


# ---------------------------------------------------------------------------
# Additional tests for should_retry
# ---------------------------------------------------------------------------


class TestShouldRetry:
    """Tests for the should_retry decision function."""

    def test_200_no_retry(self):
        """200 → no retry, no fallback."""
        assert should_retry(200, None) == (False, False)

    def test_301_no_retry(self):
        """301 → no retry, no fallback."""
        assert should_retry(301, None) == (False, False)

    def test_404_no_retry(self):
        """404 → no retry, no fallback."""
        assert should_retry(404, None) == (False, False)

    def test_410_no_retry(self):
        """410 → no retry, no fallback."""
        assert should_retry(410, None) == (False, False)

    def test_403_get_fallback(self):
        """403 → no normal retry, but try GET fallback."""
        assert should_retry(403, None) == (False, True)

    def test_405_get_fallback(self):
        """405 → no normal retry, but try GET fallback."""
        assert should_retry(405, None) == (False, True)

    def test_429_retry(self):
        """429 → retry with backoff."""
        assert should_retry(429, None) == (True, False)

    def test_503_retry(self):
        """503 → retry with backoff."""
        assert should_retry(503, None) == (True, False)

    def test_timeout_retry(self):
        """Timeout → retry."""
        assert should_retry(None, "timeout") == (True, False)

    def test_connection_reset_retry(self):
        """Connection reset → retry."""
        assert should_retry(None, "connection_reset") == (True, False)

    def test_dns_failure_no_retry(self):
        """DNS failure → no retry."""
        assert should_retry(None, "dns_failure") == (False, False)

    def test_unknown_no_retry(self):
        """Unknown status → no retry."""
        assert should_retry(None, None) == (False, False)


# ---------------------------------------------------------------------------
# Additional tests for create_request_config / create_backoff_config
# ---------------------------------------------------------------------------


class TestConfigFactories:
    """Tests for configuration factory functions."""

    def test_default_request_config(self):
        """Default config has expected values."""
        config = create_request_config()
        assert config["timeout"] == 10.0
        assert config["verify_ssl"] is True
        assert isinstance(config["user_agent"], str)
        assert len(config["user_agent"]) > 0

    def test_custom_request_config(self):
        """Custom values override defaults."""
        config = create_request_config(timeout=30.0, verify_ssl=False, user_agent="TestBot")
        assert config["timeout"] == 30.0
        assert config["verify_ssl"] is False
        assert config["user_agent"] == "TestBot"

    def test_default_backoff_config(self):
        """Default backoff config has expected values."""
        config = create_backoff_config()
        assert config["base_delay"] == 1.0
        assert config["max_delay"] == 30.0
        assert config["max_retries"] == 2
        assert config["jitter_range"] == 1.0

    def test_custom_backoff_config(self):
        """Custom values override defaults."""
        config = create_backoff_config(base_delay=2.0, max_delay=60.0, max_retries=5, jitter_range=0.5)
        assert config["base_delay"] == 2.0
        assert config["max_delay"] == 60.0
        assert config["max_retries"] == 5
        assert config["jitter_range"] == 0.5


# ---------------------------------------------------------------------------
# Test for _make_request with socket.timeout directly
# ---------------------------------------------------------------------------


class TestMakeRequestEdgeCases:
    """Edge case tests for _make_request."""

    def test_socket_timeout_direct(self):
        """Direct socket.timeout (not wrapped in URLError) is handled."""
        config = create_request_config()
        with mock.patch(
            "gh_link_auditor.network.urllib.request.urlopen",
            side_effect=socket.timeout("timed out"),
        ):
            status_code, error_type, response_time_ms, retry_after = _make_request(
                "https://example.com",
                "HEAD",
                config,
            )

        assert status_code is None
        assert error_type == "timeout"
        assert response_time_ms is not None

    def test_broken_pipe(self):
        """BrokenPipeError is classified as connection_reset."""
        config = create_request_config()
        with mock.patch(
            "gh_link_auditor.network.urllib.request.urlopen",
            side_effect=BrokenPipeError("Broken pipe"),
        ):
            status_code, error_type, response_time_ms, retry_after = _make_request(
                "https://example.com",
                "HEAD",
                config,
            )

        assert status_code is None
        assert error_type == "connection_reset"

    def test_unexpected_exception(self):
        """Unexpected exception returns 'invalid' error type."""
        config = create_request_config()
        with mock.patch(
            "gh_link_auditor.network.urllib.request.urlopen",
            side_effect=RuntimeError("Something unexpected"),
        ):
            status_code, error_type, response_time_ms, retry_after = _make_request(
                "https://example.com",
                "HEAD",
                config,
            )

        assert status_code is None
        assert error_type == "invalid"


# ---------------------------------------------------------------------------
# Integration-style test: full check_url flow with retry + fallback
# ---------------------------------------------------------------------------


class TestCheckUrlFullFlow:
    """Integration-style tests for the full check_url flow."""

    def test_429_then_405_then_get_success(self):
        """429 → retry → 405 → GET fallback → 200."""
        headers_429 = {}  # Empty headers dict (no Retry-After)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            request_obj = args[0]
            method = request_obj.get_method()

            if call_count == 1:
                # First call: HEAD → 429
                raise urllib.error.HTTPError(
                    "https://example.com",
                    429,
                    "Too Many",
                    headers_429,
                    None,
                )
            if call_count == 2 and method == "HEAD":
                # Second call: HEAD → 405
                raise urllib.error.HTTPError(
                    "https://example.com",
                    405,
                    "Not Allowed",
                    {},
                    None,
                )
            # Third call: GET → 200
            return _mock_urlopen_response(status=200)

        backoff = create_backoff_config(base_delay=0.01, max_retries=2, jitter_range=0.0)

        with mock.patch("gh_link_auditor.network.urllib.request.urlopen", side_effect=side_effect):
            with mock.patch("gh_link_auditor.network.time.sleep"):
                result = check_url("https://example.com", backoff_config=backoff)

        assert result["status"] == "ok"
        assert result["method"] == "GET"

    def test_503_exhausts_retries(self):
        """503 on every attempt exhausts retries and returns error."""
        headers_503 = {}  # Empty headers dict (no Retry-After)

        def side_effect(*args, **kwargs):
            raise urllib.error.HTTPError(
                "https://example.com",
                503,
                "Service Unavailable",
                headers_503,
                None,
            )

        backoff = create_backoff_config(base_delay=0.01, max_retries=1, jitter_range=0.0)

        with mock.patch("gh_link_auditor.network.urllib.request.urlopen", side_effect=side_effect):
            with mock.patch("gh_link_auditor.network.time.sleep"):
                result = check_url("https://example.com", backoff_config=backoff)

        assert result["status"] == "error"
        assert result["status_code"] == 503
        assert result["retries"] == 1

    def test_check_url_default_configs(self):
        """check_url works with no explicit configs (uses defaults)."""
        mock_resp = _mock_urlopen_response(status=200)
        with mock.patch("gh_link_auditor.network.urllib.request.urlopen", return_value=mock_resp):
            result = check_url("https://example.com")

        assert result["status"] == "ok"
        assert isinstance(result, dict)
        # Verify all required keys are present
        expected_keys = {"url", "status", "status_code", "method", "response_time_ms", "retries", "error"}
        assert set(result.keys()) == expected_keys
