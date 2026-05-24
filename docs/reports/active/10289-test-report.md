# 10289 - Test Report

**Issues:** #289, #291, #292, #293, #295, #296, #297
**Branch:** `289-preflight-gates-batch1`

## Test count

| Stage | Count |
|---|---|
| Before this PR | 2320 passed, 1 skipped |
| After this PR | 2347 passed, 1 skipped |
| Net | +27 new tests |

## New tests

### `tests/unit/preflight/test_gates.py` (27 tests)

- `TestGateRepoActive` (4): passes when active; fails when archived; fails when disabled; uses cache on second call
- `TestGateDeadUrlStillPresent` (4): passes when URL present; fails when absent; fails on fetch None; fails on missing candidate fields
- `TestGateDeadUrlStillDead` (3): passes on 4xx; passes on unreachable; fails on 2xx
- `TestGateCandidateUrlAlive` (3): passes on 200; passes on redirect→2xx (final_url surfaced); fails on 404
- `TestGateNoDuplicatePr` (4): passes when no open PRs; fails when open PR mentions dead URL; fails when mentions candidate URL; passes defensively when gh_get returns non-list
- `TestGateNoMarkdownCorruption` (2): passes on safe replacement; fails on unbalanced paren in dead URL
- `TestGateStarsFloor` (3): passes at/above floor; fails below floor; custom floor override
- `TestHardGatesRegistry` (1): registry has exactly 7 gates with the expected names

### `tests/unit/tools/test_preflight_check.py::TestRunPreflightDispatch` (3 new tests)

- `test_passing_gate_continues_to_pass_verdict`
- `test_failing_gate_short_circuits` (asserts later gates do NOT run after a fail)
- `test_score_too_low_when_components_below_threshold`

## Modified existing tests

`tests/unit/tools/test_preflight_check.py`:
- All 4 `TestRunPreflightScaffold` tests pass `gates=[]` to exercise scaffold semantics
- 4 `TestMain` tests get a `_patch_gates_empty` helper

`tests/unit/tools/test_derive_replacement_prs.py`:
- `TestDeriveAndSubmit` autouse fixture `_bypass_hard_gates` monkeypatches `HARD_GATES` to `[]` for every test in the class
- `TestMain` gets the same autouse fixture

## Dependency injection pattern (no MagicMock)

Each gate accepts optional collaborator kwargs:

- `http_check: Callable[[str], dict]` for `gate_dead_url_still_dead`, `gate_candidate_url_alive`
- `content_fetch: Callable[[str, str], str | None]` for `gate_dead_url_still_present`
- `gh_get: Callable[[str], dict | list | None]` for `gate_no_duplicate_pr`
- `floor: int` for `gate_stars_floor`

Tests inject lambdas; production code uses module-level defaults (`network.check_url`, `subprocess.run("gh api ...")`, `GitHubContentsClient`, `fetch_repo_metadata`). No MagicMock added; the pattern matches the existing `tests/fakes/http.py` philosophy of typed-fake injection over module patching.

`monkeypatch.setattr("gh_link_auditor.preflight.gates.fetch_repo_metadata", ...)` is used for the cache-helper tests because the helper builds the call internally. This matches existing `tests/unit/test_repo_quality.py` patterns.

## Lint

| Check | Result |
|---|---|
| `poetry run ruff format --check .` | clean |
| `poetry run ruff check .` | clean |

## Coverage on new production code

`src/gh_link_auditor/preflight/gates.py` (256 lines): every gate exercised by pass + fail tests. The cache-helper has both first-call (cache miss → fetch + store) and second-call (cache hit) coverage. Each gate's evidence dict is asserted on at least one test. Project hard rule ≥95% met.

## No regressions

`poetry run pytest -q`: **2347 passed, 1 skipped**.
