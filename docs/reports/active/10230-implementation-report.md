# 10230 Implementation Report

**Issue:** #230
**Branch:** `230-liveness-persistence`

## Changes

| File | Change |
|---|---|
| `src/gh_link_auditor/bulk_scan/config.py` | Added `LIVENESS_CACHE_TTL_HOURS = 720` (30 days). Legacy `URL_CACHE_TTL_HOURS = 24` retained as alias. |
| `src/gh_link_auditor/bulk_scan/liveness.py` | `check_urls_bulk` gets optional `on_result: Callable[[str, dict], None]` callback. Invoked from main thread (sqlite-safe) after each future completes. |
| `src/gh_link_auditor/bulk_scan/runner.py` | New `_liveness_result_from_cache(c)` reconstructs result-shape from cache row. `run_liveness` now reads `url_check_cache` first, builds the result dict from cache hits, probes only the misses, and writes each fresh probe back via callback. |
| `tests/unit/bulk_scan/test_liveness.py` (new) | 5 tests for `check_urls_bulk(on_result=...)`. |
| `tests/unit/bulk_scan/test_runner.py` (new) | 13 tests covering: first-run-probes-all, second-run-uses-cache, crash-recovery-only-reprobes-misses, empty-findings, cache-hit-shape, alive/dead reconstruction, persist-TTL-correctness, plus 6 reconstruction unit tests. |
| `docs/lld/active/LLD-230.md` | New LLD. |

## Behavior change

**Before:** Stage 2 produced ~442k URL probe results in an in-memory dict that was discarded if the process died. Any restart re-probed all URLs.

**After:** Each probe writes to `url_check_cache` immediately. Restart reads cache; only un-cached or TTL-expired URLs get re-probed.

## Concurrency

`check_urls_bulk` uses `ThreadPoolExecutor`. The `on_result` callback is invoked from the main thread (inside the `for fut in as_completed(...)` loop), NOT from worker threads — so sqlite writes are serialized and need no extra locking.

## Cache TTL

30 days. Bulk runs span days; restarts can happen up to weeks after the original kickoff (this week's incident: power cut → operator-away for 7 days → resume). Older entries are still valid signal: a URL dead a month ago is overwhelmingly likely still dead. False-positives (live URL stale-cached as dead) only matter if they affect Stage 3 — and Stage 3 still queries the actual GH API for resolution candidates regardless of cached liveness.

## Verification

- 18 new tests, all pass
- Full suite: see test report
- `ruff check` + `ruff format`: clean

## Out of scope

- Bulk SELECT for cache reads. Per-URL loop is fine — sqlite handles 442k point selects in well under a second.
- Sharing cache across machines.
- TTL-based selective re-probing (e.g., always re-check 4xx after 24h but trust 2xx for 30d). Pure-TTL is simpler and the cost of being wrong is low.
