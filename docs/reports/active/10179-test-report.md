# Test Report: #179 refresh README and CONTRIBUTING

## Local verification

This is a docs-only PR. No code changes, no new tests, no regressions to the test suite.

`poetry run python -m pytest --co -q` from the worktree still collects **1764 tests** (same as baseline post-#177 merge). No tests reference README.md or CONTRIBUTING.md content, so the doc edits don't affect any assertion.

### Spot checks

- All internal links in README go to relative paths that exist (`CONTRIBUTING.md`, `docs/lld/`, `docs/adrs/`, `docs/reports/`, `CLAUDE.md`).
- All commands listed in README are runnable as written:
  - `poetry install` ✓ (works in the worktree's fresh venv)
  - `poetry run python -m gh_link_auditor.cli.main` ✓ (this is the real entry, verified via `cli/main.py:30 prog="ghla"`)
- All standards listed in CONTRIBUTING match enforced behavior:
  - Ruff config in `pyproject.toml:7-12` matches `target-version = "py310"`, line-length 120, `select = ["E", "F", "W", "I"]`.
  - pytest-timeout, pytest-cov in `[dependency-groups]` at `pyproject.toml:33-38`.

## CI verification

This PR runs through the same gate as code PRs (`Test` + `Lint` + `auto-review` + `pr-sentinel`). Test will re-run the unchanged suite for a green tick.

## Coverage

N/A — no production code changed.

## Out of scope

- Adding a `[project.scripts] ghla = "..."` entry to make `ghla` an actual shell command. README points readers to the `python -m` invocation that exists today.
