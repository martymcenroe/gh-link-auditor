```python
"""Core HTTP request wrapper module for gh-link-auditor.

Abstracts urllib complexity and header management for HTTP requests.
Implements exponential backoff with jitter per standard 00007 and
produces results compatible with JSON report schema 00008.

See: LLD-009 (Issue #9) for design rationale.
"""

from __future__ import annotations

import http.client
import random
import socket
import ssl
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from typing import TypedDict


# ---------------------------------------------------------------------------
# Configuration data structures (LLD §2.3)
# ---------------------------------------------------------------------------

class RequestConfig(TypedDict):
    """Configuration for HTTP requests."""

    timeout: float       # Request timeout in seconds (default: 10.0)
    verify_ssl: bool     # Whether to verify SSL certificates (default: True)
    user_agent: str      # User-Agent header value


class BackoffConfig(TypedDict):
    """Configuration for retry backoff per standard 00007."""

    base_delay: float    # Initial delay in seconds (default: 1.0)
    max_delay: float     # Maximum delay ceiling (default: 30.0)
    max_retries: int     # Maximum retry attempts (default: 2)
    jitter_range: float  # Random jitter 0 to this value (default: 1.0)


class RequestResult(TypedDict):
    """Result of an HTTP request, compatible with 00008 schema."""

    url: str                     # The requested URL
    status: str                  # ok, error, timeout, failed, disconnected, invalid
    status_code: int | None      # HTTP status code or None
    method: str                  # HEAD or GET
    response_time_ms: int | None  # Response time in milliseconds
    retries: int                 # Number of retries attempted
    error: str | None            # Error description if not ok


# ---------------------------------------------------------------------------
# Default User-Agent
# ---------------------------------------------------------------------------

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/58.0.3029.110 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Factory functions (LLD §2.4)
# ---------------------------------------------------------------------------

def create_request_config(
    timeout: float = 10.0,
    verify_ssl: bool = True,
    user_agent: str | None = None,
) -> RequestConfig:
    """Create a request configuration with sensible defaults.

    Args:
        timeout: Request timeout in seconds.
        verify_ssl: Whether to verify SSL certificates.
        user_agent: Custom User-Agent string. Defaults to a common browser UA.

    Returns:
        A ``RequestConfig`` dictionary.
    """
    return RequestConfig(
        timeout=timeout,
        verify_ssl=verify_ssl,
        user_agent=user_agent if user_agent is not None else _DEFAULT_USER_AGENT,
    )


def create_backoff_config(
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    max_retries: int = 2,
    jitter_range: float = 1.0,
) -> BackoffConfig:
    """Create a backoff configuration per standard 00007.

    Args:
        base_delay: Initial delay in seconds before first retry.
        max_delay: Hard ceiling on any single delay.
        max_retries: Total retry attempts (not including the initial request).
        jitter_range: Upper bound of uniform random jitter added to each delay.

    Returns:
        A ``BackoffConfig`` dictionary.
    """
    return BackoffConfig(
        base_delay=base_delay,
        max_delay=max_delay,
        max_retries=max_retries,
        jitter_range=jitter_range,
    )


# ---------------------------------------------------------------------------
# Backoff helpers (LLD §2.4)
# ---------------------------------------------------------------------------

def calculate_backoff_delay(
    attempt: int,
    config: BackoffConfig,
    retry_after: int | None = None,
) -> float:
    """Calculate delay for a retry attempt with exponential backoff and jitter.

    Formula from standard 00007::

        delay = min(base_delay * (2 ^ attempt) + jitter, max_delay)

    If a ``retry_after`` value is provided (from HTTP Retry-After header),
    the returned delay is ``max(retry_after, calculated_delay)`` capped at
    ``max_delay``.

    Args:
        attempt: Zero-based retry attempt number (0 = first retry).
        config: Backoff configuration.
        retry_after: Optional server-requested delay in seconds.

    Returns:
        Delay in seconds before the next retry.
    """
    jitter = random.uniform(0.0, config["jitter_range"])  # noqa: S311
    calculated = config["base_delay"] * (2 ** attempt) + jitter
    if retry_after is not None:
        calculated = max(retry_after, calculated)
    return min(calculated, config["max_delay"])


def should_retry(status_code: int | None, error_type: str | None) -> tuple[bool, bool]:
    """Determine if a request should be retried based on response.

    Decision table per standard 00007:

    - 429 / 503 / timeout / connection_reset → retry with backoff
    - 403 / 405 → don't retry normally, but try GET fallback
    - 404 / 410 / 2xx–3xx / DNS failure → never retry

    Args:
        status_code: HTTP status code, or ``None`` if no response.
        error_type: Error classification string, or ``None`` on success.

    Returns:
        Tuple of ``(should_retry, try_get_fallback)``.
    """
    # Error-type based decisions (no HTTP response received)
    if error_type == "timeout":
        return True, False
    if error_type == "connection_reset":
        return True, False
    if error_type == "dns_failure":
        return False, False

    # Status-code based decisions
    if status_code is not None:
        if 200 <= status_code < 400:
            return False, False
        if status_code in (404, 410):
            return False, False
        if status_code in (403, 405):
            return False, True
        if status_code in (429, 503):
            return True, False
        # Other 4xx/5xx — don't retry
        return False, False

    # Unknown situation — don't retry
    return False, False


# ---------------------------------------------------------------------------
# Internal helpers (LLD §2.4)
# ---------------------------------------------------------------------------

def _create_ssl_context(verify: bool) -> ssl.SSLContext:
    """Create an SSL context with the specified verification setting.

    Args:
        verify: If ``True``, uses default certificate verification.
            If ``False``, disables hostname checking and certificate verification.

    Returns:
        Configured ``ssl.SSLContext``.
    """
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _parse_retry_after(header_value: str | None) -> int | None:
    """Parse Retry-After header value to seconds.

    Supports both integer seconds and HTTP-date formats per RFC 7231 §7.1.3.

    Args:
        header_value: Raw Retry-After header string, or ``None``.

    Returns:
        Delay in integer seconds, or ``None`` if unparsable / absent.
    """
    if header_value is None:
        return None

    # Try integer seconds first
    try:
        return int(header_value)
    except ValueError:
        pass

    # Try HTTP-date format (e.g. "Wed, 21 Oct 2015 07:28:00 GMT")
    try:
        target_dt = parsedate_to_datetime(header_value)
        # Calculate seconds from now; floor at 0
        delay = int((target_dt.timestamp() - time.time()))
        return max(delay, 0)
    except (ValueError, TypeError):
        pass

    return None


def _make_request(
    url: str,
    method: str,
    config: RequestConfig,
) -> tuple[int | None, str | None, int | None, str | None]:
    """Make a single HTTP request (internal helper).

    Args:
        url: The URL to request.
        method: HTTP method (``"HEAD"`` or ``"GET"``).
        config: Request configuration.

    Returns:
        Tuple of ``(status_code, error_type, response_time_ms, retry_after_header)``.

        - ``status_code``: HTTP status code, or ``None`` on connection-level errors.
        - ``error_type``: One of ``"timeout"``, ``"dns_failure"``,
          ``"connection_reset"``, ``"invalid"``, or ``None`` on success/HTTP error.
        - ``response_time_ms``: Wall-clock response time in milliseconds, or ``None``.
        - ``retry_after_header``: Raw ``Retry-After`` header value, or ``None``.
    """
    ctx = _create_ssl_context(config["verify_ssl"])
    headers = {"User-Agent": config["user_agent"]}
    req = urllib.request.Request(url, headers=headers, method=method)

    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=config["timeout"], context=ctx) as response:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            retry_after = response.headers.get("Retry-After")
            return response.status, None, elapsed_ms, retry_after
    except urllib.error.HTTPError as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        return exc.code, None, elapsed_ms, retry_after
    except urllib.error.URLError as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        reason_str = str(exc.reason)
        if "timed out" in reason_str or isinstance(exc.reason, socket.timeout):
            return None, "timeout", elapsed_ms, None
        # DNS / name resolution failures
        if isinstance(exc.reason, OSError):
            return None, "dns_failure", elapsed_ms, None
        return None, "dns_failure", elapsed_ms, None
    except socket.timeout:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return None, "timeout", elapsed_ms, None
    except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError):
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return None, "connection_reset", elapsed_ms, None
    except Exception:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return None, "invalid", elapsed_ms, None


# ---------------------------------------------------------------------------
# Status mapping helpers
# ---------------------------------------------------------------------------

def _classify_status(status_code: int | None, error_type: str | None) -> str:
    """Map a response to a 00008-schema status string.

    Args:
        status_code: HTTP status code or ``None``.
        error_type: Error classification or ``None``.

    Returns:
        One of: ``"ok"``, ``"error"``, ``"timeout"``, ``"failed"``,
        ``"disconnected"``, ``"invalid"``.
    """
    if error_type == "timeout":
        return "timeout"
    if error_type == "connection_reset":
        return "disconnected"
    if error_type == "dns_failure":
        return "failed"
    if error_type == "invalid":
        return "invalid"

    if status_code is not None:
        if 200 <= status_code < 400:
            return "ok"
        return "error"

    return "invalid"


def _build_error_message(status_code: int | None, error_type: str | None) -> str | None:
    """Build a human-readable error description.

    Args:
        status_code: HTTP status code or ``None``.
        error_type: Error classification or ``None``.

    Returns:
        Error string, or ``None`` if the request was successful.
    """
    if error_type == "timeout":
        return "Request timed out"
    if error_type == "connection_reset":
        return "Remote server disconnected"
    if error_type == "dns_failure":
        return "DNS resolution failed"
    if error_type == "invalid":
        return "Unexpected error during request"

    if status_code is not None:
        if 200 <= status_code < 400:
            return None
        return f"HTTP {status_code}"

    return "No response received"


# ---------------------------------------------------------------------------
# Public API (LLD §2.4 / §2.5)
# ---------------------------------------------------------------------------

def check_url(
    url: str,
    request_config: RequestConfig | None = None,
    backoff_config: BackoffConfig | None = None,
) -> RequestResult:
    """Check a single URL with retry logic and HEAD→GET fallback.

    Implements the full request flow per standards 00007 and 00008:

    1. Send a HEAD request.
    2. On 403/405 — fall back to GET (once, not counted as a retry).
    3. On 429/503/timeout/connection-reset — exponential backoff retry.
    4. On 404/410/DNS-failure — return immediately, no retry.

    Args:
        url: The URL to check.
        request_config: HTTP request configuration. Uses sensible defaults
            if ``None``.
        backoff_config: Retry backoff configuration per 00007. Uses sensible
            defaults if ``None``.

    Returns:
        A ``RequestResult`` dictionary compatible with 00008 schema.
    """
    if request_config is None:
        request_config = create_request_config()
    if backoff_config is None:
        backoff_config = create_backoff_config()

    method = "HEAD"
    retries = 0
    get_fallback_attempted = False

    # Use a while loop (per reviewer suggestion) for cleaner retry/fallback logic.
    while True:
        status_code, error_type, response_time_ms, retry_after_header = _make_request(
            url, method, request_config,
        )

        # Success — 2xx/3xx
        if status_code is not None and 200 <= status_code < 400:
            return RequestResult(
                url=url,
                status="ok",
                status_code=status_code,
                method=method,
                response_time_ms=response_time_ms,
                retries=retries,
                error=None,
            )

        retry_ok, try_get = should_retry(status_code, error_type)

        # HEAD→GET fallback (403/405) — not counted as a retry
        if try_get and not get_fallback_attempted:
            method = "GET"
            get_fallback_attempted = True
            continue

        # Permanent failures — return immediately
        if not retry_ok:
            return RequestResult(
                url=url,
                status=_classify_status(status_code, error_type),
                status_code=status_code,
                method=method,
                response_time_ms=response_time_ms,
                retries=retries,
                error=_build_error_message(status_code, error_type),
            )

        # Retryable — check if we have retries left
        if retries < backoff_config["max_retries"]:
            retry_after_seconds = _parse_retry_after(retry_after_header)
            delay = calculate_backoff_delay(retries, backoff_config, retry_after_seconds)
            time.sleep(delay)
            retries += 1
            continue

        # Exhausted retries — return final status
        return RequestResult(
            url=url,
            status=_classify_status(status_code, error_type),
            status_code=status_code,
            method=method,
            response_time_ms=response_time_ms,
            retries=retries,
            error=_build_error_message(status_code, error_type),
        )
```
