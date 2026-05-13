# Implementation Report: #179 refresh README and CONTRIBUTING

## Summary

The README and CONTRIBUTING were written when the project was barely past first commit. README listed shipped capabilities (HITL, graph expansion, state DB) as "Planned" and the only usage example was `python check_links.py` — no mention of the `ghla` CLI, the LangGraph pipeline, the fork→PR workflow, the unified DB, trust escalation, batch engine, or the metrics dashboard. CONTRIBUTING said tests would exist "once the test suite is established" — there are 1,764+ today, and the project rule is ≥95% coverage mandatory.

This PR replaces both files with current, accurate descriptions of what's actually shipped.

## Changes

### `README.md` (rewritten)
- New "Status" table distinguishes shipped from planned.
- Quickstart uses `poetry install` + `poetry run python -m gh_link_auditor.cli.main run …` (the actual entry point — there's no `ghla` shell command registered; that's a separate gap, not part of this PR).
- Subcommand reference table covers all five subcommands wired into `cli/main.py` (`run`, `batch`, `blacklist`, `metrics`, `recheck`).
- Documents the two zero-dep scripts at the repo root (`check_links.py`, `hitl_console.py`) for ad-hoc use.
- Points to `docs/lld/`, `docs/adrs/`, `docs/reports/`, and `CLAUDE.md` for deeper context.
- One forward-looking entry in the Status table: hostile-maintainer comment detection (#178).

### `CONTRIBUTING.md` (rewritten)
- Replaced "tests exist once the test suite is established" with current reality (1,764+ tests, ~100s locally).
- Added the worktree-per-issue workflow that matches the project's actual practice.
- Documented the six-step PR workflow: LLD → tests → implement → lint → reports → PR.
- Listed the standards already enforced by tooling: poetry-only (never `pip`), ruff lint+format, ≥95% coverage, no `MagicMock` (shared fakes in `tests/fakes/`), DNS mocking required for redirect tests.
- Noted the role of `pr-sentinel` and `Cerberus-AZ` in the merge gate.

## Files modified

| File | Change |
|------|--------|
| `README.md` | Rewritten — status table, quickstart, subcommands, scripts, docs map |
| `CONTRIBUTING.md` | Rewritten — workflow, standards, test reality |

## Out of scope

- **`ghla` shell entry point.** README documents the `poetry run python -m gh_link_auditor.cli.main` invocation that exists today. Adding `[project.scripts]` to wire `ghla` directly is a separate small change worth filing if anyone wants the shorter form.
- **No changes to actual project behavior.** Docs-only.
