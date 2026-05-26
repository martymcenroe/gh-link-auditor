"""Core HTTP request wrapper module for gh-link-auditor.

Abstracts urllib complexity and header management for HTTP requests.
Implements exponential backoff with jitter per standard 00007 and
produces results compatible with JSON report schema 00008.

See: LLD-009 (Issue #9) for design rationale.
"""

from __future__ import annotations

import http.client
import ipaddress
import logging
import random
import socket
import ssl
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from typing import NotRequired, TypedDict
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration data structures (LLD §2.3)
# ---------------------------------------------------------------------------


class RequestConfig(TypedDict):
    """Configuration for HTTP requests."""

    timeout: float  # Request timeout in seconds (default: 10.0)
    verify_ssl: bool  # Whether to verify SSL certificates (default: True)
    user_agent: str  # User-Agent header value


class BackoffConfig(TypedDict):
    """Configuration for retry backoff per standard 00007."""

    base_delay: float  # Initial delay in seconds (default: 1.0)
    max_delay: float  # Maximum delay ceiling (default: 30.0)
    max_retries: int  # Maximum retry attempts (default: 2)
    jitter_range: float  # Random jitter 0 to this value (default: 1.0)


class RequestResult(TypedDict):
    """Result of an HTTP request, compatible with 00008 schema."""

    url: str  # The requested URL
    status: str  # ok, error, timeout, failed, disconnected, invalid
    status_code: int | None  # HTTP status code or None
    method: str  # HEAD or GET (whichever yielded the final status)
    response_time_ms: int | None  # Response time in milliseconds
    retries: int  # Number of retries attempted
    error: str | None  # Error description if not ok
    # Final URL after any redirect chain (#315 — used by preflight gate #7 / score C4).
    # Optional via NotRequired so pre-#315 call sites that build RequestResult dicts
    # without this key remain valid TypedDict constructions.
    final_url: NotRequired[str | None]
    # HEAD-specific status code (#343). Always populated when an HTTP request was
    # actually attempted; None when no HEAD request happened (e.g., invalid-URL
    # short-circuits). Lets downstream code see "URL is HEAD-strict" patterns
    # (HEAD 4xx + GET 2xx) without re-probing.
    head_status_code: NotRequired[int | None]
    # GET-specific status code (#343). None when HEAD-only succeeded and no
    # GET fallback was attempted. Populated when HEAD→GET fallback fired.
    get_status_code: NotRequired[int | None]


# ---------------------------------------------------------------------------
# Default User-Agent
# ---------------------------------------------------------------------------

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/58.0.3029.110 Safari/537.36"
)

# Modern browser UA for retry on 403 (#122)
_BROWSER_RETRY_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
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
    calculated = config["base_delay"] * (2**attempt) + jitter
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
        if status_code == 410:
            # 410 Gone is intentional permanent removal — HEAD/GET difference unlikely.
            return False, False
        if status_code in (403, 404, 405):
            # 403/405 commonly block HEAD; 404 sometimes does too (anti-crawler
            # defense on sites like Microsoft Marketplace, #193). Try GET once.
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
) -> tuple[int | None, str | None, int | None, str | None, str | None]:
    """Make a single HTTP request (internal helper).

    Args:
        url: The URL to request.
        method: HTTP method (``"HEAD"`` or ``"GET"``).
        config: Request configuration.

    Returns:
        Tuple of ``(status_code, error_type, response_time_ms, retry_after_header, final_url)``.

        - ``status_code``: HTTP status code, or ``None`` on connection-level errors.
        - ``error_type``: One of ``"timeout"``, ``"dns_failure"``,
          ``"connection_reset"``, ``"invalid"``, or ``None`` on success/HTTP error.
        - ``response_time_ms``: Wall-clock response time in milliseconds, or ``None``.
        - ``retry_after_header``: Raw ``Retry-After`` header value, or ``None``.
        - ``final_url``: Final URL after any redirects (#315). ``None`` on
          connection-level errors that produced no response.
    """
    ctx = _create_ssl_context(config["verify_ssl"])
    headers = {"User-Agent": config["user_agent"]}
    req = urllib.request.Request(url, headers=headers, method=method)

    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=config["timeout"], context=ctx) as response:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            retry_after = response.headers.get("Retry-After")
            final_url = getattr(response, "url", None) or url
            return response.status, None, elapsed_ms, retry_after, final_url
    except urllib.error.HTTPError as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        final_url = getattr(exc, "url", None) or url
        return exc.code, None, elapsed_ms, retry_after, final_url
    except urllib.error.URLError as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        reason = exc.reason
        # #261: distinguish failure classes so downstream can route per
        # category. SSL/cert is OFTEN TEMPORARY (operator note 2026-05-26
        # on issue #261): expired certs, CA chain hiccups, CDN edge issues.
        # Downstream must NOT propose removal on first cert_invalid -- defer
        # and re-check after N days instead.
        if isinstance(reason, ssl.SSLError):
            return None, "cert_invalid", elapsed_ms, None, None
        if isinstance(reason, socket.timeout) or "timed out" in str(reason):
            return None, "timeout", elapsed_ms, None, None
        if isinstance(reason, ConnectionRefusedError):
            return None, "connection_refused", elapsed_ms, None, None
        if isinstance(reason, socket.gaierror):
            return None, "dns_failure", elapsed_ms, None, None
        if isinstance(reason, OSError):
            # Catch-all transport error: network unreachable, EHOSTUNREACH,
            # other low-level OS errors. Distinct from DNS / refused / cert
            # so downstream can decide retry policy per class.
            return None, "transport_error", elapsed_ms, None, None
        return None, "transport_error", elapsed_ms, None, None
    except ssl.SSLError:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return None, "cert_invalid", elapsed_ms, None, None
    except socket.timeout:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return None, "timeout", elapsed_ms, None, None
    except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError):
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return None, "connection_reset", elapsed_ms, None, None
    except ConnectionRefusedError:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return None, "connection_refused", elapsed_ms, None, None
    except Exception:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return None, "invalid", elapsed_ms, None, None


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
    # #261: cert_invalid, connection_refused, transport_error all map to
    # "failed" for the legacy schema field; the granular category lives
    # on the error_type / failure_class side of the RequestResult.
    if error_type in {"cert_invalid", "connection_refused", "transport_error"}:
        return "failed"
    if error_type == "invalid":
        return "invalid"

    if status_code is not None:
        if 200 <= status_code < 400:
            return "ok"
        return "error"

    return "invalid"


# ---------------------------------------------------------------------------
# Failure-class classification (#261)
# ---------------------------------------------------------------------------


# Granular error-type values that ``_make_request`` may produce. Each
# represents a distinct probe-failure mode -- the downstream "what to do"
# decision (defer / retry / propose removal / no-op) routes off these.
ERROR_TYPES_TEMPORARY: frozenset[str] = frozenset(
    {
        # #261 operator note 2026-05-26: cert errors are OFTEN TEMPORARY.
        # Expired certs renewed within hours; CA chain hiccups; CDN edge
        # issues. NEVER propose removal on first cert_invalid -- defer.
        "cert_invalid",
        # Server load / network jitter -- often transient.
        "timeout",
        # Network-unreachable / EHOSTUNREACH / other low-level OS errors
        # that may be operator-side (VPN flap, DNS resolver bouncing).
        "transport_error",
        # Server temporarily closed the socket.
        "connection_reset",
    }
)
ERROR_TYPES_DURABLE: frozenset[str] = frozenset(
    {
        # DNS resolution returned NXDOMAIN. More likely permanent than
        # cert errors, but DNS can hiccup too -- caller may still want to
        # re-check after N days before proposing removal.
        "dns_failure",
        # Service explicitly refused connection on the port. Durable in
        # the sense that the operator/service has to act to bring it back.
        "connection_refused",
    }
)
ERROR_TYPES_UNKNOWN: frozenset[str] = frozenset({"invalid"})


def classify_failure(error_type: str | None) -> str:
    """Map a granular probe error_type to a coarse handling class.

    Returns one of:

    - ``"temporary"`` -- cert / timeout / transport / connection reset.
      Downstream should defer (re-check after N days) before proposing
      any removal PR. The operator clarified on #261 (2026-05-26) that
      cert_invalid in particular is frequently transient.
    - ``"durable"`` -- DNS NXDOMAIN / connection refused. More likely to
      survive across re-checks, but still warrants a defer-then-confirm
      cycle before a removal proposal.
    - ``"unknown"`` -- catch-all "invalid" bucket; treat conservatively.
    - ``"none"`` -- error_type is None (no failure observed).
    """
    if error_type is None:
        return "none"
    if error_type in ERROR_TYPES_TEMPORARY:
        return "temporary"
    if error_type in ERROR_TYPES_DURABLE:
        return "durable"
    return "unknown"


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
    if error_type == "cert_invalid":
        # #261: surface the granular class so operator logs distinguish
        # cert from DNS-dead. Action class is "temporary" -- see
        # classify_failure().
        return "SSL/TLS certificate error"
    if error_type == "connection_refused":
        return "Connection refused"
    if error_type == "transport_error":
        return "Network transport error"
    if error_type == "invalid":
        return "Unexpected error during request"

    if status_code is not None:
        if 200 <= status_code < 400:
            return None
        return f"HTTP {status_code}"

    return "No response received"


# ---------------------------------------------------------------------------
# CDN detection (#198) — used to gate the None-status stealth fallback
# ---------------------------------------------------------------------------

_CDN_RANGES = (
    ipaddress.ip_network("104.16.0.0/12"),  # Cloudflare main
    ipaddress.ip_network("172.64.0.0/13"),  # Cloudflare
    ipaddress.ip_network("151.101.0.0/16"),  # Fastly
    ipaddress.ip_network("199.232.0.0/16"),  # Fastly
)


def _resolves_to_cdn(url: str) -> bool:
    """Return True if the URL's hostname resolves to a known-bot-fronting CDN.

    Used to gate the expensive stealth-browser fallback: only fire it for hosts
    that are likely returning bot-block errors (Cloudflare / Fastly), not for
    genuinely dead hosts. Lookups go through the OS resolver and are typically
    cached. Failure modes (DNS error, missing hostname) return False so we
    don't accidentally trigger stealth for a broken URL.

    See LLD-198.
    """
    try:
        host = urlparse(url).hostname
    except ValueError:
        return False
    if not host:
        return False
    try:
        _, _, ip_list = socket.gethostbyname_ex(host)
    except (socket.gaierror, OSError):
        return False
    for ip_str in ip_list:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if any(ip in net for net in _CDN_RANGES):
            return True
    return False


# ---------------------------------------------------------------------------
# Headless-browser fallback (#190)
# ---------------------------------------------------------------------------

_CHALLENGE_TITLE_MARKERS = ("checking your browser", "just a moment")


def _headless_browser_get(url: str, timeout_s: float = 20.0) -> RequestResult:
    """Verify a URL by loading it via real Chrome with stealth patches.

    For URLs that fail HTTP probing due to JavaScript anti-bot challenges
    (Cloudflare-style 403 to non-browser clients). Uses ``channel='chrome'``
    so it reuses the user's installed Chrome — no Chromium download.

    Returns ``status='ok'`` if navigation completed and the final page is
    not a challenge page. See LLD-190 for the heuristic.

    Args:
        url: URL to probe.
        timeout_s: Hard cap for navigation. Defaults to 20s — enough for
            most JS challenges to resolve.

    Returns:
        ``RequestResult`` with ``method='HEADLESS'``.
    """
    start = time.monotonic()
    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth
    except ImportError as exc:
        return RequestResult(
            url=url,
            status="error",
            status_code=None,
            method="HEADLESS",
            response_time_ms=0,
            retries=0,
            error=f"playwright unavailable: {exc}",
            final_url=None,
        )

    final_landing_url: str | None = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context()
                page = context.new_page()
                Stealth().apply_stealth_sync(page)
                response = page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=int(timeout_s * 1000),
                )
                final_status = response.status if response is not None else None
                final_title = (page.title() or "").lower()
                # Capture the final URL after any client-side / HTTP redirects (#315).
                # getattr-with-default keeps test fakes that don't expose `url` working.
                final_landing_url = getattr(page, "url", None) or url
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 — third-party error surface is wide
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return RequestResult(
            url=url,
            status="error",
            status_code=None,
            method="HEADLESS",
            response_time_ms=elapsed_ms,
            retries=0,
            error=f"headless probe failed: {exc}",
            final_url=final_landing_url,
        )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    if any(marker in final_title for marker in _CHALLENGE_TITLE_MARKERS):
        return RequestResult(
            url=url,
            status="error",
            status_code=final_status,
            method="HEADLESS",
            response_time_ms=elapsed_ms,
            retries=0,
            error="still on JS challenge page after networkidle",
            final_url=final_landing_url,
        )

    return RequestResult(
        url=url,
        status="ok",
        status_code=(final_status if final_status is not None and final_status < 400 else 200),
        method="HEADLESS",
        response_time_ms=elapsed_ms,
        retries=0,
        error=None,
        final_url=final_landing_url,
    )


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
    browser_ua_attempted = False
    # Track the status from each method separately so callers can detect
    # HEAD-strict URLs (HEAD 4xx + GET 2xx) without re-probing (#343).
    head_status_recorded: int | None = None
    get_status_recorded: int | None = None

    # Use a while loop (per reviewer suggestion) for cleaner retry/fallback logic.
    while True:
        status_code, error_type, response_time_ms, retry_after_header, final_url = _make_request(
            url,
            method,
            request_config,
        )
        if method == "HEAD":
            head_status_recorded = status_code
        else:
            get_status_recorded = status_code

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
                final_url=final_url,
                head_status_code=head_status_recorded,
                get_status_code=get_status_recorded,
            )

        retry_ok, try_get = should_retry(status_code, error_type)

        # HEAD→GET fallback (403/405) — not counted as a retry
        if try_get and not get_fallback_attempted:
            logger.info(
                "url_check head_to_get_fallback url=%s head_status=%s",
                url,
                head_status_recorded,
            )
            method = "GET"
            get_fallback_attempted = True
            continue

        # Browser UA retry on 403 after GET fallback (#122)
        if status_code == 403 and get_fallback_attempted and not browser_ua_attempted:
            browser_ua_attempted = True
            # Preserve all keys (including the optional allow_headless flag, #190)
            # and only override user_agent.
            request_config = {**request_config, "user_agent": _BROWSER_RETRY_UA}  # type: ignore[typeddict-item]
            continue

        # Headless-browser fallback (#190) — gated by opt-in flag.
        # Only triggers after the modern-UA retry has also failed with 403.
        if (
            status_code == 403 and browser_ua_attempted and request_config.get("allow_headless")  # type: ignore[typeddict-item]
        ):
            return _headless_browser_get(
                url,
                timeout_s=request_config["timeout"] * 2,
            )

        # CDN-fronted None status — also try stealth (#198).
        # Cloudflare / Fastly often block bot probes at the transport layer
        # (connection reset / timeout) rather than returning 403. When the
        # host resolves to a known CDN, the real-browser path is worth the
        # cost; for genuinely unreachable hosts, the _resolves_to_cdn check
        # short-circuits to False and we avoid spending 10-20s on stealth.
        if (
            status_code is None
            and error_type in {"connection_reset", "timeout"}
            and request_config.get("allow_headless")  # type: ignore[typeddict-item]
            and _resolves_to_cdn(url)
        ):
            return _headless_browser_get(
                url,
                timeout_s=request_config["timeout"] * 2,
            )

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
                final_url=final_url,
                head_status_code=head_status_recorded,
                get_status_code=get_status_recorded,
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
            final_url=final_url,
            head_status_code=head_status_recorded,
            get_status_code=get_status_recorded,
        )
