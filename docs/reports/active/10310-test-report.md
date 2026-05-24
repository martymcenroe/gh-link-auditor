# 10310 - Test Report

**Issues:** #310, #311, #312, #313
**Branch:** `310-preflight-tests-ops`

## Test count

| Stage | Count |
|---|---|
| Before this PR | 2431 passed, 1 skipped |
| After this PR | 2441 passed, 2 skipped |
| Net | +10 tests (1 of the new tests is the live test which is skipped without `--live`) |

## New tests

### `tests/integration/test_preflight_fixtures.py` (6 scenarios, 6 tests)

Each scenario exercises `run_preflight` with injected gate/score collaborators:

- `TestScenarioPassingAndreavidali` — all 9 wrapped gates PASS → verdict PASS
- `TestScenarioArchivedRepo` — gate #2 fail (archived) → HARD_GATE_FAILED
- `TestScenarioAntiAiRepo` — gate #1 fail (subagent HOSTILE) → HARD_GATE_FAILED
- `TestScenarioDeadUrlResurrected` — gate #5 fail (dead URL now 200) → HARD_GATE_FAILED
- `TestScenarioLowStars` — gate #10 fail (3 stars vs floor 20) → HARD_GATE_FAILED
- `TestScenarioDuplicatePr` — gate #8 fail (open PR mentions URL) → HARD_GATE_FAILED

### `tests/integration/test_preflight_live.py` (1 test, opt-in)

`test_preflight_against_andreavidali_live` — `@pytest.mark.live`, runs only when `pytest --live` is passed. Hits real GitHub API + real `claude --print`. Asserts PASS + score ≥ 90 + evidence spot-check.

### `tests/integration/test_preflight_prompts.py` (4 tests)

- 3 golden-file tests (one per prompt) — file exists, matches golden, has "single token" grammar hint
- 1 FakeSubagent recording sanity test

## Test infrastructure

`tests/conftest.py`:
- `pytest_addoption` registers `--live` and `--update-goldens` CLI flags
- `pytest_collection_modifyitems` auto-skips `@pytest.mark.live` tests unless `--live` is passed
- `update_goldens` fixture exposes the flag to golden-file tests

`pyproject.toml`:
- `live` marker added to the `markers` list (alongside the existing `integration` marker)

## Tool A summary grouping (#313)

`_print_summary` now reads the `skipped` list and partitions on `reason == "preflight_needs_review"`. Operator-review entries go above the regular skip list with a `>>> OPERATOR REVIEW NEEDED <<<` banner that points at `data/preflight-reports/`. The OPERATOR REVIEW NEEDED banner inside the markdown report (from #286) remains unchanged.

## Lint

| Check | Result |
|---|---|
| `poetry run ruff format --check .` | clean |
| `poetry run ruff check .` | clean (3 auto-fixes for import ordering in new test files) |

## No regressions

`poetry run pytest -q`: **2441 passed, 2 skipped**.
