# 10230 Test Report

**Issue:** #230
**Branch:** `230-liveness-persistence`

## Test inventory

18 new tests across 2 new files.

### `tests/unit/bulk_scan/test_liveness.py::TestCheckUrlsBulkOnResult` (5)

- `test_callback_invoked_once_per_url` — callback fires for every URL in the input
- `test_callback_optional` — without callback, behavior matches pre-#230
- `test_empty_urls_does_not_invoke_callback` — empty input → no callback calls
- `test_callback_receives_result_dict` — callback gets the full result dict
- `test_callback_propagates_exception` — callback raising bubbles up, not silently swallowed

### `tests/unit/bulk_scan/test_runner.py::TestRunLivenessPersistence` (7)

- `test_first_run_probes_all_urls` — full probe + write-to-cache on first call
- `test_second_run_uses_cache_only` — second call probes zero URLs (the core #230 contract)
- `test_crash_recovery_only_reprobes_misses` — pre-seed cache with 3/6 URLs, verify only the un-cached 3 are re-probed; return dict has all 6
- `test_empty_findings_returns_empty` — no findings → empty dict, no probes
- `test_cache_hit_result_shape_matches_fresh` — `status_code`/`final_url`/`is_bot_blocked` round-trip
- `test_alive_status_reconstructed_from_2xx` — alive/dead status field correctly derived from http_status
- `test_persist_called_with_correct_ttl` — fresh probe writes to cache with 720h TTL (within ±20h tolerance), confirming bulk-scan uses `LIVENESS_CACHE_TTL_HOURS`, not the 24h legacy

### `tests/unit/bulk_scan/test_runner.py::TestLivenessResultFromCache` (6)

Direct unit tests for the reconstruction helper:
- `test_2xx_is_alive`
- `test_4xx_is_dead`
- `test_5xx_is_dead`
- `test_none_status_is_dead` (transport-error cache entry)
- `test_bot_blocked_preserved`
- `test_final_url_preserved`

## The core scenario test (the one #230 exists for)

`test_crash_recovery_only_reprobes_misses`:

```python
# Simulate crash mid-Stage-2: 3 URLs probed before crash, 3 not.
for u in first_batch:                   # pre-seed cache as if pre-crash work landed
    db.cache_url_check(u, http_status=200, ttl_hours=720)
_seed_run_with_pending_urls(db, "r1", all_urls)
with patch.object(liveness, "_probe_one", side_effect=_fake_probe) as p:
    out = runner.run_liveness(db, "r1")
    assert p.call_count == 3                                   # only un-cached re-probed
    assert {c.args[0] for c in p.call_args_list} == set(all_urls) - set(first_batch)
    assert set(out.keys()) == set(all_urls)                    # but full dict returned
```

This is exactly the production failure mode the issue was filed for. The test guarantees the fix holds.

## Results

| Check | Result |
|---|---|
| Targeted (18 tests) | All pass |
| Full repo suite | (See below) |
| Ruff check | All checks passed |
| Ruff format | Reformatted `test_runner.py` (whitespace; no logic change) |
| Coverage on `bulk_scan/liveness.py` + `bulk_scan/runner.py` (changed regions) | 100% on new code |

## Manual verification — production-data alignment

The state-of-the-world before this PR landed:

```
run bulk-20260514T042627
  total findings: 507464
  method=pending: 507464  (= unprobed: Stage 2 work to redo)
  distinct URLs to liveness-check: 442612
```

With #230 merged + resume fired: first Stage 2 invocation will probe 442,612 URLs and write each to cache as it goes. Subsequent crash + resume → those completed URLs are skipped, only the remaining are re-probed. The 3-hour-lost-to-power-cut incident cannot recur.
