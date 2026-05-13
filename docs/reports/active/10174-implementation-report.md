# Implementation Report: #174 pytest + CI test job

## Summary

Wires `pytest` and `pytest-cov` into the project's poetry dev group and adds a CI workflow that runs the full test suite on every PR. Before this PR, `pytest` was not a declared dependency and CI only ran `ruff` — so test regressions could merge into main undetected.

## Changes

### `pyproject.toml`
- Added `[dependency-groups]` block with `dev = ["pytest (>=9.0.3,<10.0.0)", "pytest-cov (>=7.1.0,<8.0.0)"]`. (Poetry 2.x uses PEP 735's `[dependency-groups]` format by default for `poetry add --group dev`.)

### `poetry.lock`
- Regenerated to include `pytest`, `pytest-cov`, `coverage`, `iniconfig`, `pluggy`, `pygments`, and transitive deps.

### `.github/workflows/test.yml` (NEW)
- Triggers on `pull_request` and `push` to `main` (same as `lint.yml`).
- Python 3.12, installs poetry, runs `poetry install`, runs `poetry run python -m pytest --cov=src --cov-report=term --cov-report=xml`.
- Uploads `coverage.xml` as an artifact (always, even on failure) so coverage trends can be inspected.

### `tests/unit/repo_scout/test_stargazer_harvester.py`
- Fixed two time-boundary tests that hardcoded ISO dates (`2026-02-01`, `2025-10-01`). The original dates were chosen as "within the 6-month window" when written but `2025-10-01` is now 7+ months in the past, so `_is_recently_active(...)` correctly returns `False` and the test fails. Replaced with `datetime.now(timezone.utc) - timedelta(days=N)` so the dates float with the clock. Other hardcoded dates in the file (`2026-02-01`, `2026-02-15`) are still within the window today but will break in October 2026 — flagged for follow-up.

## Test count baseline

`pytest --co` collects **1,749 tests** in the post-archive tree (1,731 unit + 18 integration). MEMORY.md last recorded 1,705 after #148-#150 — the +44 since then are unaccounted-for in memory and will be reconciled after this PR.
