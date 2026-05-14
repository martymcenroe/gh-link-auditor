"""Rate-limit-aware GitHub REST API client for the bulk scan (#224).

Wraps ``httpx.Client`` with three protections against secondary rate limits:

1. **Inter-request throttle** — enforces a minimum delay between requests
   (default 750ms = ~80 req/min, well under any documented GH limit).
2. **Quota watermark** — when ``X-RateLimit-Remaining`` drops below a floor,
   sleep until ``X-RateLimit-Reset``.
3. **Retry on 429 / secondary rate limit** — honors ``Retry-After``, falls back
   to exponential backoff up to 15 min. Max 5 retries.

GitHub's secondary rate limit fires on burst patterns (many requests in a short
window) even when the primary 5K/hr is far from exhausted. This is the one that
took down the first 7500-repo run on 2026-05-14.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class GitHubRateLimitedClient:
    """Sync httpx wrapper enforcing GH API rate-limit etiquette."""

    def __init__(
        self,
        token: str | None = None,
        *,
        per_request_delay_s: float = 0.75,
        low_watermark: int = 100,
        max_retries: int = 5,
        max_backoff_s: float = 900.0,
        base_backoff_s: float = 2.0,
        timeout_s: float = 30.0,
    ) -> None:
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "gh-link-auditor-bulk",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(headers=headers, timeout=timeout_s)
        self._per_request_delay = per_request_delay_s
        self._low_watermark = low_watermark
        self._max_retries = max_retries
        self._max_backoff = max_backoff_s
        self._base_backoff = base_backoff_s

        self._last_request_t = 0.0
        self._remaining: int | None = None
        self._reset_at: datetime | None = None
        # Telemetry
        self.total_requests = 0
        self.total_429s = 0
        self.total_secondary_limits = 0
        self.total_sleep_s = 0.0

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """GET with full rate-limit machinery applied."""
        return self._request("GET", url, **kwargs)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GitHubRateLimitedClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            self._wait_for_quota()
            self._wait_for_request_spacing()
            r = self._client.request(method, url, **kwargs)
            self._last_request_t = time.monotonic()
            self.total_requests += 1
            self._update_quota(r.headers)
            if not self._is_rate_limited(r):
                return r
            self._record_rate_limit(r)
            if attempt >= self._max_retries:
                logger.warning(
                    "max retries exhausted on %s — returning %d response",
                    url,
                    r.status_code,
                )
                return r
            delay = self._compute_backoff(r, attempt)
            logger.warning(
                "rate-limited (%d) on %s — backing off %.1fs (attempt %d/%d)",
                r.status_code,
                url,
                delay,
                attempt + 1,
                self._max_retries,
            )
            self.total_sleep_s += delay
            time.sleep(delay)
        # Unreachable — loop returns or sleeps then continues
        raise RuntimeError("unreachable")

    def _wait_for_quota(self) -> None:
        """If remaining quota is below floor, sleep until reset."""
        if self._remaining is None or self._remaining > self._low_watermark:
            return
        if self._reset_at is None:
            return
        now = datetime.now(timezone.utc)
        sleep_s = (self._reset_at - now).total_seconds() + 1.0
        if sleep_s <= 0:
            return
        logger.warning(
            "quota low (%d remaining); sleeping %.0fs until reset",
            self._remaining,
            sleep_s,
        )
        self.total_sleep_s += sleep_s
        time.sleep(sleep_s)

    def _wait_for_request_spacing(self) -> None:
        elapsed = time.monotonic() - self._last_request_t
        if elapsed >= self._per_request_delay:
            return
        sleep_s = self._per_request_delay - elapsed
        self.total_sleep_s += sleep_s
        time.sleep(sleep_s)

    def _update_quota(self, headers: httpx.Headers) -> None:
        remaining = headers.get("X-RateLimit-Remaining")
        if remaining is not None:
            try:
                self._remaining = int(remaining)
            except ValueError:
                pass
        reset = headers.get("X-RateLimit-Reset")
        if reset is not None:
            try:
                self._reset_at = datetime.fromtimestamp(int(reset), tz=timezone.utc)
            except ValueError:
                pass

    def _is_rate_limited(self, r: httpx.Response) -> bool:
        """True if the response indicates a primary OR secondary rate limit."""
        if r.status_code == 429:
            return True
        if r.status_code == 403:
            # Secondary rate limit: 403 with remaining>0 and body says so.
            text = (r.text or "").lower()
            if "secondary rate limit" in text or "abuse" in text:
                return True
            # Primary exhaustion: 403 with X-RateLimit-Remaining == 0
            if self._remaining is not None and self._remaining == 0:
                return True
        return False

    def _record_rate_limit(self, r: httpx.Response) -> None:
        if r.status_code == 429:
            self.total_429s += 1
        else:
            self.total_secondary_limits += 1

    def _compute_backoff(self, r: httpx.Response, attempt: int) -> float:
        """Prefer Retry-After header; else exponential + jitter."""
        retry_after = r.headers.get("Retry-After")
        if retry_after:
            try:
                delay = float(retry_after)
                return min(delay, self._max_backoff)
            except ValueError:
                pass
        # GH may also send `X-RateLimit-Reset` epoch when 403'd
        if r.status_code == 403 and self._reset_at is not None:
            now = datetime.now(timezone.utc)
            delta = (self._reset_at - now).total_seconds() + 1.0
            if delta > 0:
                return min(delta, self._max_backoff)
        # Exponential fallback: 2s, 4s, 8s, 16s, 32s ... capped at max_backoff
        base = self._base_backoff * (2**attempt)
        jitter = random.uniform(0, base * 0.25)
        return min(base + jitter, self._max_backoff)
