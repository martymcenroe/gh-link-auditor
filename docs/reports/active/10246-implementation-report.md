# Implementation Report: #246 flaky test_low_watermark_sleeps

## Summary

`tests/unit/batch/test_rate_limiter.py::TestBackpressure::test_low_watermark_sleeps` set `X-RateLimit-Reset` to `now + 60s`, then called `asyncio.run(rl.acquire())` which awaits a real `asyncio.sleep(60)`. CI's `pytest-timeout = 60s` raced that exact sleep duration — on a slow runner, normal test-setup overhead pushed the actual wall-clock past 60s and the test timed out.

This caused the spurious CI failure on PR #271 (the post-#268 status-line bundle) and forced a close/reopen to retrigger CI. Issue #246 was filed previously identifying this exact race; this PR fixes it.

## Fix

Stub `asyncio.sleep` with `monkeypatch` so `acquire()` returns immediately while still recording what duration it asked for. The test's contract is unchanged: it verifies (a) backpressure activated, (b) `acquire()` requested a positive sleep. Removing the actual wall-clock wait removes the race.

```python
async def _fake_sleep(seconds: float) -> None:
    sleeps.append(seconds)

monkeypatch.setattr(
    "gh_link_auditor.batch.rate_limiter.asyncio.sleep",
    _fake_sleep,
)

asyncio.run(rl.acquire())

assert sleeps, "expected at least one asyncio.sleep call"
assert sleeps[0] > 0
```

Patching the module-attribute path (`rate_limiter.asyncio.sleep`) keeps the patch scoped to the rate_limiter's usage. `asyncio.run()` itself does not call `asyncio.sleep`, so the patch is safe.

## Test count

Unchanged: **2158 passed, 1 skipped**.

## Suite time

- Before: ~125s (the flaky test slept ~60s when it passed)
- After: ~68s (the test runs in 0.16s)

That's ~46% faster — a nice bonus, but the real win is determinism.

## Files modified

| File | Change |
|------|--------|
| `tests/unit/batch/test_rate_limiter.py` | swap real `asyncio.sleep` for a recording stub via `monkeypatch.setattr` |

No library code changed. The `AdaptiveRateLimiter.acquire()` contract is unchanged.

## Out of scope

- The other backpressure test (`test_between_watermarks_proportional_delay`) uses a 10s reset window and goes through the `delay = ratio * min(max_delay, 10.0)` path — actually sleeps ~5.5s of wall-clock. Not flaky (well under the 60s timeout), but ALSO not great for suite speed. Could mock the same way as a follow-up if suite time matters more.
- Refactoring `AdaptiveRateLimiter.acquire()` to accept an injected sleep function would let tests run with no asyncio at all. Bigger change; not needed for the fix.
