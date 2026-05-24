# 10289 - Implementation Report

**Issues:** #289 (archived), #291 (URL still present), #292 (dead URL still dead), #293 (candidate URL alive), #295 (duplicate PR), #296 (markdown corruption), #297 (stars floor)
**Branch:** `289-preflight-gates-batch1`
**Umbrella:** #281

## Summary

PR-δ: ships the 7 non-subagent hard gates as `src/gh_link_auditor/preflight/gates.py`, plus dispatch wiring in `run_preflight()` and the `HARD_GATES` registry. PR-ε will append 3 subagent-using gates (anti_ai, blacklist, redirect_target).

Each gate is a small callable returning `GateResult(name, passed, reason, evidence)`. Real-world collaborators (`network.check_url`, `repo_quality.fetch_repo_metadata`, `GitHubContentsClient`, `gh api`) are reachable as defaults but every gate accepts dependency-injection kwargs (`http_check`, `content_fetch`, `gh_get`) so tests stay offline and use the `tests/fakes/` patterns.

Cache integration: `gate_repo_active` and `gate_stars_floor` share a `_get_cached_or_fetch_repo_meta` helper that hits `preflight_repo_meta_cache` (#285) before falling back to a fresh GitHub fetch.

## Gates shipped

| Gate | Issue | Failure mode |
|---|---|---|
| `gate_repo_active` | #289 | archived or disabled repo |
| `gate_dead_url_still_present` | #291 | upstream file no longer contains the dead URL |
| `gate_dead_url_still_dead` | #292 | dead URL returns 2xx (it's been resurrected) |
| `gate_candidate_url_alive` | #293 | candidate URL is not 2xx (broken replacement) |
| `gate_no_duplicate_pr` | #295 | open PR already mentions either URL |
| `gate_no_markdown_corruption` | #296 | `str.replace` would corrupt markdown (delegates to existing `_is_safely_replaceable`) |
| `gate_stars_floor` | #297 | repo has fewer than 20 stars (operator floor) |

## Dispatch update

`tools/preflight_check.run_preflight` now iterates `HARD_GATES` and short-circuits to `HARD_GATE_FAILED` on the first failing gate. The `gates=` kwarg lets tests inject an empty / synthetic registry — used by `TestRunPreflightScaffold` to keep scaffold semantics testable and by `TestDeriveAndSubmit` + `TestMain` autouse fixtures to bypass real GitHub/network collaborators.

When no `score_components` are wired (PR-η / PR-θ haven't landed), the dispatch returns `score=threshold` so PASS verdicts actually pass tool A's threshold check.

## Files

### New

- `src/gh_link_auditor/preflight/gates.py` — 7 gate functions + `HARD_GATES` registry + `_get_cached_or_fetch_repo_meta` helper + `DEFAULT_STARS_FLOOR = 20`
- `tests/unit/preflight/test_gates.py` — 27 tests across 7 `TestGate*` classes + `TestHardGatesRegistry`

### Modified

- `tools/preflight_check.py`
  - Imports `HARD_GATES`
  - `run_preflight` accepts `gates=` and `score_components=` overrides (default to `HARD_GATES` / empty)
  - Real gate dispatch: short-circuit on first fail; score check uses sum of score_breakdown when populated, falls back to `threshold` when empty
- `tests/unit/tools/test_preflight_check.py`
  - `TestRunPreflightScaffold` tests pass `gates=[]` to exercise scaffold semantics without invoking real gates
  - NEW `TestRunPreflightDispatch` class — 3 tests for the gate dispatch (pass continues to PASS; fail short-circuits; score < threshold → SCORE_TOO_LOW)
  - `TestMain` tests get a `_patch_gates_empty` helper that monkeypatches `HARD_GATES` to `[]`
- `tests/unit/tools/test_derive_replacement_prs.py`
  - `TestDeriveAndSubmit` gets an autouse `_bypass_hard_gates` fixture
  - `TestMain` gets the same autouse fixture
  - (TestPreflightIntegration unaffected — its tests already patch `run_preflight` directly)

## Verification

| Check | Result |
|---|---|
| `poetry run pytest -q` | **2347 passed**, 1 skipped (was 2320 after PR-γ; +27 from PR-δ) |
| `poetry run ruff format --check .` | clean |
| `poetry run ruff check .` | clean |
| `git grep -i -E '(A\+\+\|PRs filed\|contribution graph\|green square\|naked ambition)'` | 0 hits |
| Real gates use real collaborators by default (no monkey-patching in production) | yes |
| Each gate testable offline via injected `http_check` / `content_fetch` / `gh_get` | yes |
| `preflight_repo_meta_cache` (from #285) reused via shared `_get_cached_or_fetch_repo_meta` | yes |

## Out of scope

- Anti-AI text scan (#288), blacklist (#290), redirect-target subagent (#294) — PR-ε
- Score components (#298–#309) — PR-η + PR-θ
- Recorded-fixture integration tests (#310) — PR-ι
- E2E verification (#314) — operator
