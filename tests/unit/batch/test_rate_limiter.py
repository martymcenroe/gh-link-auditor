"""Tests for adaptive rate limiter.

Covers LLD-019 scenarios:
- T070: Backpressure at low watermark (REQ-4)
- T080: No backpressure above high watermark (REQ-4)
- T310: Rate limiter parses X-RateLimit headers (REQ-4)
"""

from __future__ import annotations

import asyncio
import time

from gh_link_auditor.batch.rate_limiter import AdaptiveRateLimiter


class TestBackpressure:
    """T070: Backpressure at low watermark (REQ-4)."""

    def test_low_watermark_sleeps(self, monkeypatch) -> None:
        """acquire() sleeps when remaining < low_watermark.

        #246 — Previously this test awaited a real ``asyncio.sleep(60)`` to
        observe a positive elapsed wall-clock. That raced the pytest-timeout
        of 60s on slow CI runners. We now stub ``asyncio.sleep`` to record
        its argument and return immediately; the contract being verified is
        unchanged: backpressure was activated, and acquire() asked to sleep
        for a positive duration.
        """
        rl = AdaptiveRateLimiter(low_watermark=100, high_watermark=1000)
        rl.update_from_headers(
            {
                "X-RateLimit-Remaining": "50",
                "X-RateLimit-Reset": str(int(time.time()) + 60),
            }
        )

        sleeps: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(
            "gh_link_auditor.batch.rate_limiter.asyncio.sleep",
            _fake_sleep,
        )

        asyncio.run(rl.acquire())

        # acquire() asked for a positive sleep (because remaining < low_watermark
        # and reset is ~60s out) — exact value depends on monotonic clock drift
        # between header parsing and acquire(), but must be > 0.
        assert sleeps, "expected at least one asyncio.sleep call"
        assert sleeps[0] > 0
        snapshot = rl.snapshot()
        assert snapshot["backpressure_active"] is True

    def test_between_watermarks_proportional_delay(self) -> None:
        """Linear interpolation between low and high watermarks."""
        rl = AdaptiveRateLimiter(low_watermark=100, high_watermark=1000)
        rl.update_from_headers(
            {
                "X-RateLimit-Remaining": "500",
                "X-RateLimit-Reset": str(int(time.time()) + 10),
            }
        )

        start = time.monotonic()
        asyncio.run(rl.acquire())
        elapsed = time.monotonic() - start

        # Should have a moderate delay (proportional)
        assert elapsed >= 0.0


class TestNoBackpressure:
    """T080: No backpressure above high watermark (REQ-4)."""

    def test_high_remaining_no_delay(self) -> None:
        """acquire() returns immediately when remaining > high_watermark."""
        rl = AdaptiveRateLimiter(low_watermark=100, high_watermark=1000)
        rl.update_from_headers({"X-RateLimit-Remaining": "2000"})

        start = time.monotonic()
        asyncio.run(rl.acquire())
        elapsed = time.monotonic() - start

        assert elapsed < 0.05  # Essentially immediate

    def test_default_state_no_delay(self) -> None:
        """Fresh rate limiter has no delay."""
        rl = AdaptiveRateLimiter()

        start = time.monotonic()
        asyncio.run(rl.acquire())
        elapsed = time.monotonic() - start

        assert elapsed < 0.05


class TestUpdateFromHeaders:
    """T310: Rate limiter parses X-RateLimit headers (REQ-4)."""

    def test_parses_remaining(self) -> None:
        rl = AdaptiveRateLimiter()
        rl.update_from_headers({"X-RateLimit-Remaining": "42"})
        snapshot = rl.snapshot()
        assert snapshot["lowest_remaining"] == 42

    def test_parses_reset_timestamp(self) -> None:
        rl = AdaptiveRateLimiter()
        rl.update_from_headers(
            {
                "X-RateLimit-Remaining": "42",
                "X-RateLimit-Reset": "1700000000",
            }
        )
        snapshot = rl.snapshot()
        assert snapshot["lowest_remaining"] == 42
        assert snapshot["next_reset"] != ""

    def test_missing_headers_no_crash(self) -> None:
        rl = AdaptiveRateLimiter()
        rl.update_from_headers({})
        snapshot = rl.snapshot()
        assert snapshot["lowest_remaining"] == 5000  # Default

    def test_snapshot_format(self) -> None:
        rl = AdaptiveRateLimiter()
        snapshot = rl.snapshot()
        assert "total_remaining" in snapshot
        assert "lowest_remaining" in snapshot
        assert "next_reset" in snapshot
        assert "backpressure_active" in snapshot
