# Test Report: #268/#269/#270 status-line observability bundle

## Verification

This bundle adds observability fields to `tools/finish_stage3.py`'s status line and status file. Pure arithmetic + string formatting + a deque sliding window. Verified by:

1. **Smoke test** — three Stats states exercised: fresh / mid-run-5-candidates / lots-skipped-no-candidates.
2. **Full suite** — 2158 passed, 1 skipped (no regressions; no test touched).
3. **Manual eyeball** — output matches the design in the LLD-style sketch.

### Smoke test output

```
CASE 1 (fresh — nothing processed):
  [13:00:58] stage3 0/100,000 (0.0%) skipped=0 investigated=0 yield=n/a cands+=0 rate=0/min (5m: 0/min) ETA=? last_cand=never

CASE 2 (100 invs, 5 cand, started 5m ago, last cand 8m ago):
  [13:00:58] stage3 100/100,000 (0.1%) skipped=0 investigated=100 yield=5.0% cands+=5 rate=20/min (5m: 20/min) ETA=83.3h last_cand=8m

CASE 3 (200 invs, 0 cand, lots skipped):
  [13:00:58] stage3 280/100,000 (0.3%) skipped=80 investigated=200 yield=0.0% cands+=0 rate=28/min (5m: 28/min) ETA=59.4h last_cand=never
```

All three cases render cleanly. `yield=n/a` in case 1, `yield=0.0%` in case 3 (200 invs, 0 cand). `last_cand=never` until a candidate surfaces, then `8m` etc. `recent_rate` falls back to lifetime when fewer than 2 samples exist.

### Suite regression

```
$ poetry run pytest -q --tb=line
2158 passed, 1 skipped, 1 warning in 139.29s
```

Same count as post-#267.

### Lint + format

```
$ ruff check tools/finish_stage3.py
All checks passed!
$ ruff format tools/finish_stage3.py
1 file left unchanged
```

## What's NOT tested

- A pytest unit test of `Stats.yield_pct()` / `recent_rate_per_min()` / `time_since_last_cand_str()`. The `Stats` class lives inside `finish_stage3.py` which eager-loads the entire LinkDetective chain at module import (#265). Standing up a test that imports just `Stats` would either require refactoring `Stats` into a separate module or paying the heavy import cost on every test run. The methods are pure arithmetic; the smoke test exercises the rendering correctness. A proper unit-testable home for `Stats` is a follow-up refactor.
- Integration test with a live Stage 3 run. The operator restarts Stage 3 manually; the next per-minute status line shows the new format.

## CI verification

Standard gate: Test, Lint, auto-review, pr-sentinel. The tool isn't imported by tests or the package, so the only CI signal is Lint catching syntax/import breakage.

## Operator action

After merge: stop the current `finish_stage3.py` run, restart with the same command. The next status line will use the new format. Watch `last_cand=` — if it stays at `never` for >10 min after restart, the pipeline isn't producing candidates and we need to dig. Watch `yield=` — should hover around 0.5-1% on this corpus based on the 14-candidates-in-75-min sample from the current run.

## Out of scope

- Multi-line periodic dump (every 5 min, more detail). Different design.
- Same treatment for the other three tool scripts (`finish_stage1`, `finish_stage2`, `detect_languages`). They have different `Stats` shapes and no "candidates" concept; not a 1:1 port.
