# Test Report: #246 flaky test_low_watermark_sleeps

## Verification

### Targeted

```
$ poetry run pytest tests/unit/batch/test_rate_limiter.py::TestBackpressure::test_low_watermark_sleeps -v
PASSED [100%]
1 passed in 0.16s
```

0.16s vs. the previous ~60s.

### Full rate_limiter file

```
$ poetry run pytest tests/unit/batch/test_rate_limiter.py -v
8 passed in 5.32s
```

All 8 tests in the file still green.

### Full suite

```
$ poetry run pytest -q --tb=line
2158 passed, 1 skipped, 1 warning in 68.67s
```

No regressions. Suite time dropped from ~125s to ~68s because the flaky test no longer wastes 60s on every clean run.

### Lint + format

```
$ ruff format --check tests/unit/batch/test_rate_limiter.py
1 file already formatted
$ ruff check tests/unit/batch/test_rate_limiter.py
All checks passed!
```

## Reliability

The previous test was racing the timeout because real `asyncio.sleep(60)` + test setup overhead occasionally exceeded the 60s pytest-timeout marker on slow CI runners. With `asyncio.sleep` stubbed, there's no wall-clock dependency — the test completes in deterministic sub-millisecond time. No timeout race possible.

I ran the test 10 times locally in a tight loop (`for i in {1..10}; do pytest tests/unit/batch/test_rate_limiter.py::TestBackpressure::test_low_watermark_sleeps; done`); all 10 passed in well under 1s each.

## CI verification

Standard gate: Test, Lint, auto-review, pr-sentinel. The Test job, which is what was failing intermittently, should now pass deterministically.

## What's NOT tested

- A test that proves the test itself is no longer flaky under load. The original failure mode requires a slow CI runner with co-tenant noise; locally I can't reliably reproduce it. The structural fix (no wall-clock dependency) eliminates the race by construction.

## Out of scope

- Mocking `asyncio.sleep` in `test_between_watermarks_proportional_delay` too (currently sleeps ~5.5s). Not racing the timeout, so not in scope here. Could be done for suite-speed reasons in a follow-up.
- Refactoring `acquire()` to accept an injected sleep callable. Bigger change; not required for this fix.
