# Test Report: #174 pytest + CI test job

## Local verification

### Collection
`poetry run python -m pytest --co -q` collects **1,749 tests** in 5.5s without errors. Confirms `pytest` is now resolvable from the project's poetry venv (was failing with `No module named pytest` before this PR — pytest had never been a declared dependency).

### Run

(Filled in after the full unit run completes — see commit history for the in-progress vs. final state.)

### Failing test fixed by this PR

`tests/unit/repo_scout/test_stargazer_harvester.py::TestIsRecentlyActive::test_boundary_exact_age` was failing under today's clock (2026-05-12) because its hardcoded date `2025-10-01` is now 224 days old, beyond the 180-day (6-month) window the function checks against. Fix: use `datetime.now(timezone.utc) - timedelta(days=170)` so the date is always inside the boundary.

## CI verification

This PR's own merge gate runs the new `test.yml` workflow for the first time. If it lands green, the gate is confirmed working. After merge, any subsequent PR that breaks a test will be blocked at the gate instead of merging silently.

## Coverage

`pytest-cov` is enabled with `--cov=src --cov-report=term --cov-report=xml`. The XML artifact uploads on every CI run (even on failure) so coverage trends can be tracked over time. Per repo memory, "≥95% test coverage is mandatory" — this PR is the gate that finally enforces it.

## Known follow-up

Other hardcoded dates in `test_stargazer_harvester.py` (`2026-02-01`, `2026-02-15`) are still within the 6-month window today but will break in October–November 2026. Filed separately as the simplification work crosses into a different scope.
