"""Adaptive rate limiter with backpressure based on GitHub API headers.

See LLD-019 §2.4 for AdaptiveRateLimiter specification.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from gh_link_auditor.batch.models import RateLimitSnapshot


class AdaptiveRateLimiter:
    """Rate limiter that adapts based on GitHub API rate limit headers."""

    def __init__(
        self, low_watermark: int = 100, high_watermark: int = 1000
    ) -> None:
        """Initialize with backpressure thresholds.

        Args:
            low_watermark: Below this remaining count, apply maximum backpressure.
            high_watermark: Above this, no throttling applied.
        """
        self.low_watermark = low_watermark
        self.high_watermark = high_watermark
        self._remaining: int = 5000
        self._reset_at: datetime | None = None
        self._backpressure_active: bool = False

    async def acquire(self) -> None:
        """Wait if necessary before making an API call."""
        if self._remaining >= self.high_watermark:
            return

        if self._remaining < self.low_watermark:
            self._backpressure_active = True
            sleep_time = self._calculate_sleep_to_reset()
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            return

        # Linear interpolation between low and high watermarks
        self._backpressure_active = False
        ratio = (self.high_watermark - self._remaining) / (
            self.high_watermark - self.low_watermark
        )
        max_delay = self._calculate_sleep_to_reset()
        delay = ratio * min(max_delay, 10.0)
        if delay > 0:
            await asyncio.sleep(delay)

    def _calculate_sleep_to_reset(self) -> float:
        """Calculate seconds until rate limit reset."""
        if self._reset_at is None:
            return 1.0
        now = datetime.now(timezone.utc)
        delta = (self._reset_at - now).total_seconds()
        return max(delta, 0.0)

    def update_from_headers(self, headers: dict[str, str]) -> None:
        """Update rate limit state from GitHub response headers.

        Args:
            headers: Response headers containing X-RateLimit-* values.
        """
        remaining_str = headers.get("X-RateLimit-Remaining", "")
        if remaining_str:
            self._remaining = int(remaining_str)

        reset_str = headers.get("X-RateLimit-Reset", "")
        if reset_str:
            self._reset_at = datetime.fromtimestamp(
                int(reset_str), tz=timezone.utc
            )

    def snapshot(self) -> RateLimitSnapshot:
        """Return current rate limit state for progress display."""
        next_reset = ""
        if self._reset_at:
            next_reset = self._reset_at.isoformat()

        return RateLimitSnapshot(
            total_remaining=self._remaining,
            lowest_remaining=self._remaining,
            next_reset=next_reset,
            backpressure_active=self._backpressure_active,
        )
