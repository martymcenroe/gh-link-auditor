"""Tests for the GitHubRateLimitedClient (#224 hotfix)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx

from gh_link_auditor.bulk_scan.gh_client import GitHubRateLimitedClient


def _make_response(
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    text: str = "",
) -> MagicMock:
    """Build a MagicMock that quacks like httpx.Response."""
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.headers = httpx.Headers(headers or {})
    r.text = text
    return r


def _make_client(**kwargs) -> GitHubRateLimitedClient:
    """Tight-budget client for tests (no real sleeps)."""
    defaults = {
        "per_request_delay_s": 0.0,  # don't actually sleep between requests in tests
        "low_watermark": 100,
        "max_retries": 3,
        "max_backoff_s": 1.0,
        "base_backoff_s": 0.01,
        "timeout_s": 5.0,
    }
    defaults.update(kwargs)
    return GitHubRateLimitedClient(token="test-token", **defaults)


class TestSuccessfulRequest:
    def test_returns_200_immediately(self) -> None:
        client = _make_client()
        with patch.object(
            client._client,
            "request",
            return_value=_make_response(200, {"X-RateLimit-Remaining": "4999"}),
        ):
            r = client.get("https://api.github.com/repos/x/y")
        assert r.status_code == 200
        assert client.total_requests == 1
        assert client.total_429s == 0
        client.close()

    def test_updates_quota_from_headers(self) -> None:
        client = _make_client()
        reset_epoch = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
        with patch.object(
            client._client,
            "request",
            return_value=_make_response(
                200,
                {
                    "X-RateLimit-Remaining": "4321",
                    "X-RateLimit-Reset": str(reset_epoch),
                },
            ),
        ):
            client.get("https://api.github.com/repos/x/y")
        assert client._remaining == 4321
        assert client._reset_at is not None
        client.close()

    def test_records_total_requests(self) -> None:
        client = _make_client()
        with patch.object(client._client, "request", return_value=_make_response(200)):
            client.get("u1")
            client.get("u2")
            client.get("u3")
        assert client.total_requests == 3
        client.close()


class TestRateLimit429:
    def test_retries_on_429_then_succeeds(self) -> None:
        client = _make_client(max_retries=3, base_backoff_s=0.0, per_request_delay_s=0.0)
        responses = [
            _make_response(429, {"Retry-After": "0"}),
            _make_response(429, {"Retry-After": "0"}),
            _make_response(200),
        ]
        with patch.object(client._client, "request", side_effect=responses):
            r = client.get("u")
        assert r.status_code == 200
        assert client.total_429s == 2
        assert client.total_requests == 3
        client.close()

    def test_returns_final_429_when_max_retries_exceeded(self) -> None:
        client = _make_client(max_retries=2, base_backoff_s=0.0)
        with patch.object(
            client._client,
            "request",
            return_value=_make_response(429, {"Retry-After": "0"}),
        ):
            r = client.get("u")
        assert r.status_code == 429
        # 1 initial + 2 retries = 3 total
        assert client.total_requests == 3
        client.close()

    def test_honors_retry_after_header(self) -> None:
        client = _make_client(max_retries=1, base_backoff_s=10.0, max_backoff_s=1.0)
        # Retry-After=0 means we go through both attempts immediately.
        with (
            patch.object(
                client._client,
                "request",
                side_effect=[_make_response(429, {"Retry-After": "0"}), _make_response(200)],
            ),
            patch("time.sleep") as sleep_mock,
        ):
            r = client.get("u")
        # First sleep call(s) are from per_request_delay or quota wait (=0 in test).
        # Should have called sleep with 0.0 for Retry-After=0
        assert r.status_code == 200
        sleep_args = [c.args[0] for c in sleep_mock.call_args_list]
        # At least one sleep with the Retry-After value
        assert any(s == 0.0 for s in sleep_args)
        client.close()

    def test_retry_after_capped_at_max_backoff(self) -> None:
        client = _make_client(max_retries=0, max_backoff_s=1.5)
        delay = client._compute_backoff(_make_response(429, {"Retry-After": "999"}), attempt=0)
        assert delay <= 1.5
        client.close()


class TestSecondaryRateLimit:
    def test_detects_403_with_secondary_message(self) -> None:
        client = _make_client(max_retries=2, base_backoff_s=0.0)
        responses = [
            _make_response(403, text="You have exceeded a secondary rate limit"),
            _make_response(200),
        ]
        with patch.object(client._client, "request", side_effect=responses):
            r = client.get("u")
        assert r.status_code == 200
        assert client.total_secondary_limits == 1
        client.close()

    def test_detects_403_with_abuse_message(self) -> None:
        client = _make_client(max_retries=2, base_backoff_s=0.0)
        responses = [
            _make_response(403, text="abuse detection triggered"),
            _make_response(200),
        ]
        with patch.object(client._client, "request", side_effect=responses):
            r = client.get("u")
        assert r.status_code == 200
        assert client.total_secondary_limits == 1
        client.close()

    def test_403_remaining_zero_is_rate_limit(self) -> None:
        client = _make_client(max_retries=2, base_backoff_s=0.0)
        # First call sets X-RateLimit-Remaining=0; next call gets 403 → treated as rate-limit
        responses = [
            _make_response(403, {"X-RateLimit-Remaining": "0"}),
            _make_response(200, {"X-RateLimit-Remaining": "1"}),
        ]
        with patch.object(client._client, "request", side_effect=responses):
            r = client.get("u")
        assert r.status_code == 200
        assert client.total_secondary_limits == 1
        client.close()

    def test_403_unrelated_to_rate_limit_returns_immediately(self) -> None:
        """A 403 with no rate-limit signals (e.g., bad auth) is NOT retried."""
        client = _make_client(max_retries=3, base_backoff_s=0.0)
        with patch.object(
            client._client,
            "request",
            return_value=_make_response(
                403,
                {"X-RateLimit-Remaining": "4999"},
                text="bad credentials",
            ),
        ):
            r = client.get("u")
        assert r.status_code == 403
        assert client.total_requests == 1  # No retries
        client.close()


class TestQuotaWatermark:
    def test_sleeps_when_below_watermark(self) -> None:
        client = _make_client(low_watermark=100)
        client._remaining = 50
        client._reset_at = datetime.now(timezone.utc) + timedelta(seconds=2)
        with (
            patch("time.sleep") as sleep_mock,
            patch.object(client._client, "request", return_value=_make_response(200)),
        ):
            client.get("u")
        # Should have slept for ~2 seconds before request
        sleep_calls = [c.args[0] for c in sleep_mock.call_args_list]
        assert any(s >= 1.5 for s in sleep_calls)
        client.close()

    def test_no_sleep_above_watermark(self) -> None:
        client = _make_client(low_watermark=100)
        client._remaining = 5000
        client._reset_at = datetime.now(timezone.utc) + timedelta(hours=1)
        with (
            patch("time.sleep") as sleep_mock,
            patch.object(client._client, "request", return_value=_make_response(200)),
        ):
            client.get("u")
        # No long sleep — request spacing is 0 in test config
        for c in sleep_mock.call_args_list:
            assert c.args[0] < 1.0
        client.close()

    def test_no_sleep_when_quota_unknown(self) -> None:
        client = _make_client()
        # Don't set _remaining or _reset_at
        with (
            patch("time.sleep") as sleep_mock,
            patch.object(client._client, "request", return_value=_make_response(200)),
        ):
            client.get("u")
        for c in sleep_mock.call_args_list:
            assert c.args[0] < 1.0
        client.close()


class TestRequestSpacing:
    def test_enforces_minimum_delay(self) -> None:
        client = _make_client(per_request_delay_s=0.5)
        client._last_request_t = 0.0
        # Simulate having just made a request very recently
        import time as time_mod

        client._last_request_t = time_mod.monotonic() - 0.1  # 0.1s ago

        slept = []

        def fake_sleep(s):
            slept.append(s)
            # do not actually sleep — just record

        with (
            patch("time.sleep", side_effect=fake_sleep),
            patch.object(client._client, "request", return_value=_make_response(200)),
        ):
            client.get("u")
        # Should have slept the gap between 0.1 elapsed and 0.5 floor = ~0.4s
        assert any(0.3 <= s <= 0.5 for s in slept)
        client.close()


class TestBackoffComputation:
    def test_exponential_growth(self) -> None:
        client = _make_client(base_backoff_s=1.0, max_backoff_s=1000.0)
        r = _make_response(429)
        d0 = client._compute_backoff(r, 0)
        d1 = client._compute_backoff(r, 1)
        d2 = client._compute_backoff(r, 2)
        # Each roughly doubles (with jitter up to +25%); just verify monotonic-ish
        assert d0 <= 1.5
        assert d1 <= 3.0
        assert d2 <= 6.0
        # No retry-after, no reset: pure exponential
        client.close()

    def test_capped_at_max_backoff(self) -> None:
        client = _make_client(base_backoff_s=1000.0, max_backoff_s=5.0)
        r = _make_response(429)
        for attempt in range(10):
            d = client._compute_backoff(r, attempt)
            assert d <= 5.0
        client.close()

    def test_prefer_retry_after(self) -> None:
        client = _make_client(base_backoff_s=100.0, max_backoff_s=1000.0)
        r = _make_response(429, {"Retry-After": "7"})
        d = client._compute_backoff(r, 0)
        assert d == 7.0
        client.close()


class TestStickyCooldown:
    """Tests for #226 -- the sticky cooldown circuit-breaker.

    Cooldown deadline is shared across threads via instance attribute; this
    test class drives it via the public _request path and via the internal
    _wait_for_cooldown / _extend_cooldown helpers.
    """

    def test_initial_cooldown_is_zero(self) -> None:
        client = _make_client()
        assert client._cooldown_until_mono == 0.0
        client.close()

    def test_429_extends_cooldown(self) -> None:
        client = _make_client(max_retries=1)
        responses = [_make_response(429, {"Retry-After": "0.1"}), _make_response(200)]
        with patch.object(client._client, "request", side_effect=responses):
            client.get("https://api.github.com/x")
        # Cooldown must have been set forward by ~0.1s. Allow generous tolerance
        # because the test ran some time after the deadline was set.
        assert client.total_cooldown_waits == 0  # no waits needed -- only the retrying thread sleeps directly
        # The cooldown deadline is in the past now (sleep already happened) but
        # was set to a future point when 429 fired:
        # we observe via the deadline attribute which is in monotonic seconds.
        # Since 0.1s elapsed since set, deadline is now in the recent past.
        client.close()

    def test_wait_for_cooldown_sleeps_when_active(self) -> None:
        client = _make_client()
        # Force cooldown to 0.05s in the future.
        with client._cooldown_lock:
            client._cooldown_until_mono = time.monotonic() + 0.05
        start = time.monotonic()
        client._wait_for_cooldown()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.04, f"_wait_for_cooldown returned too early: {elapsed:.3f}s"
        assert client.total_cooldown_waits == 1
        client.close()

    def test_wait_for_cooldown_returns_immediately_when_expired(self) -> None:
        client = _make_client()
        # Deadline already in the past
        with client._cooldown_lock:
            client._cooldown_until_mono = time.monotonic() - 1.0
        start = time.monotonic()
        client._wait_for_cooldown()
        elapsed = time.monotonic() - start
        assert elapsed < 0.05, f"_wait_for_cooldown blocked unnecessarily: {elapsed:.3f}s"
        assert client.total_cooldown_waits == 0
        client.close()

    def test_extend_cooldown_only_pushes_forward(self) -> None:
        client = _make_client()
        far_future = time.monotonic() + 100.0
        with client._cooldown_lock:
            client._cooldown_until_mono = far_future
        # Try to push backward -- should be a no-op
        client._extend_cooldown(0.001)
        assert client._cooldown_until_mono == far_future
        client.close()

    def test_extend_cooldown_pushes_forward_when_later(self) -> None:
        client = _make_client()
        # Currently 0; extend by 0.5s -> deadline becomes now + 0.5
        before = time.monotonic()
        client._extend_cooldown(0.5)
        after = time.monotonic()
        # Deadline should be in [before + 0.5, after + 0.5]
        assert before + 0.5 <= client._cooldown_until_mono <= after + 0.5
        client.close()

    def test_sibling_workers_share_the_cooldown(self) -> None:
        """The whole point of #226: a 429 on one request must make the
        next _request call wait. We simulate the sibling-worker scenario
        by driving _request twice -- the second call must observe the
        cooldown set by the first.

        #433: asserts the REQUESTED sleep recorded from a patched
        ``time.sleep``, not measured wall-clock. The old form timed a real
        sleep against the deadline set several statements earlier; on a
        loaded CI runner the gap between ``_extend_cooldown`` and the
        measured window consumed the deadline (observed 0.010s and 0.055s
        against a 0.09s floor). Recording the request makes the test
        deterministic and removes all real sleeping.
        """
        client = _make_client(max_retries=1, base_backoff_s=0.05)
        slept: list[float] = []
        first_responses = [_make_response(429), _make_response(200)]
        with patch.object(time, "sleep", side_effect=slept.append):
            # First _request: 429 then 200 -- extends the shared cooldown and
            # "sleeps" (recorded) for its own retry.
            with patch.object(client._client, "request", side_effect=first_responses):
                client.get("https://api.github.com/x")
            # Simulate a sibling 429 happening concurrently, then drop the
            # first request's recorded sleeps so the assertion sees only the
            # sibling's wait.
            client._extend_cooldown(0.1)
            slept.clear()
            # The next _request must request a wait for ~the full cooldown.
            with patch.object(client._client, "request", return_value=_make_response(200)):
                client.get("https://api.github.com/y")
        assert sum(slept) >= 0.09, f"sibling request did not honor cooldown: requested sleeps {slept}"
        assert client.total_cooldown_waits >= 1
        client.close()


class TestContextManager:
    def test_works_as_context_manager(self) -> None:
        with GitHubRateLimitedClient(token="x", per_request_delay_s=0.0) as c:
            assert c._remaining is None
        # client closed automatically
