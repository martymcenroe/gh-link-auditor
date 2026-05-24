# 1278 - Implementation Report

**Issue:** #278 — chore(scrub): remove A++/contribution-graph/harvest language from public surface; move to docs/private/
**Branch:** `278-scrub-public-surface`
**Worktree:** `gh-link-auditor-278`

## Summary

Phase A of plan `1-docs-private-gitignored-is-concurrent-mochi`. Scrubs the public surface of `gh-link-auditor` of "A++ scorecard / contribution graph / green square" framing and adds a `--campaign-allowed` flag that pauses `tools/derive_replacement_prs.py` until the operator re-confirms the public surface is clean.

## Tracked-surface scope

The plan's "Hard removals" table listed three files in `tools/` that turned out to be UNTRACKED in both worktrees — they exist only on disk in the main worktree as one-shot historical scripts. Public-surface scrub is therefore narrower than the plan implied. Adjusted scope to the actual `git grep -i -E '(A\+\+|PRs filed|contribution graph|green square|naked ambition)'` hits (3 hits each in 2 files), plus the README/dashboard rewrites the plan called out.

## Files modified (6 tracked + 1 test file)

| File | Change |
|---|---|
| `.gitignore` | Add `docs/private/` (operator-private strategy notes, never commit) |
| `README.md` | Lines 20, 21, 45 — "Campaign metrics dashboard" → "Pipeline run-metrics dashboard"; "stargazer harvesting" → "stargazer graphs"; subcommand description rewritten |
| `docs/lineage/done/22-Assemb0-0001/Assemb0-0001-001-brief.md` | Strip lines 89 (contribution-credit bullet) + 93 (contribution-graph link). Rename `#### 4. GitHub Score Impact` to `#### 4. Run-level Metrics`. Renumber the "Why This Matters" list to drop the green-square item |
| `ideas/done/22-langgraph-pipeline-and-campaign-dashboard.md` | Replace 137-line "contribution engine" pitch with a neutral 11-line stub pointing at the public artifacts that shipped from this design |
| `src/gh_link_auditor/campaign_dashboard.py` | Module + function docstrings: "campaign" → "pipeline run-metrics". Display strings ("Campaign Summary") preserved — they match the CLI subcommand name `ghla metrics campaign` and existing tests assert on them |
| `tools/derive_replacement_prs.py` | New `--campaign-allowed` flag (default `False`); `main()` exits 2 with a pause message pointing at issue #278 when the flag is absent |
| `tests/unit/tools/test_derive_replacement_prs.py` | +2 new tests, +1 assertion in `TestBuildParser::test_defaults`, +1 arg in `TestBuildParser::test_explicit_flags`, updated 2 existing `TestMain` tests to pass `--campaign-allowed` |

## Operator-local files (gitignored, in worktree only)

Created in `docs/private/` (excluded by the new `.gitignore` entry):

- `docs/private/README.md` — directory purpose, reconstitution notes
- `docs/private/strategy.md` — A++ scorecard rules verbatim from the prior public surface, plus blocklist/campaign discipline
- `docs/private/dashboard-spec.md` — full original 137-line "Clacks Network" dashboard design (moved from `ideas/done/22-...`)
- `docs/private/handoff-strategy-snippets.md` — stripped lessons-learned rows + a "words to avoid" table for future handoffs

None of these are tracked; they live only in the operator's working tree.

## Files NOT modified (out of scope per operator decision)

| File | Reason |
|---|---|
| `src/repo_scout/stargazer_harvester.py` + `docs/lld/archived/LLD-036.md` + related reports | Module name and symbol names kept (operator: don't rename modules in this PR). Symbol references are not in the banned regex. Surface-text scrub of repo_scout CLI help would be a follow-up |
| `tools/append_handoff_entry.py`, `tools/append_handoff_artifacts.py`, `tools/derive_host_blocklist.py` | UNTRACKED files in main worktree. Plan referenced them as public surface but they're not in `HEAD`. Operator's "leave alone unless asked" instruction from handoff applies |
| `src/gh_link_auditor/campaign_dashboard.py` filename | Per plan: file rename is a bigger refactor, out of scope. Only docstrings touched |
| AssemblyZero / Aletheia | Per plan decision matrix: Discworld persona and internal "harvest" stays |

## Mechanical verification (Phase A acceptance)

| Check | Result |
|---|---|
| `git grep -i -E '(A\+\+|PRs filed\|contribution graph\|green square\|naked ambition)'` | 0 hits |
| `poetry run pytest -q` | 2237 passed, 1 skipped |
| `poetry run ruff format --check .` | 234 files already formatted |
| `poetry run ruff check .` | All checks passed |
| `docs/private/` in `.gitignore` | Yes |
| `docs/private/{README,strategy,dashboard-spec,handoff-strategy-snippets}.md` exist (worktree only) | Yes |
| `tools/derive_replacement_prs.py` refuses without `--campaign-allowed` | Yes — exit code 2, pause message printed (covered by `test_main_refuses_without_campaign_allowed`) |

## Out of scope (follow-ups)

- Rename `campaign_dashboard.py` filename (operator: defer)
- Rename `stargazer_harvester.py` filename + symbols (operator: defer)
- Scrub "harvest" wording in `src/repo_scout/` CLI help text and module docstrings (manual review item from plan acceptance; not in plan's "Files to modify" table)
- Phase B (PR preflight feature) — separate issue per plan
- Phase C (community-feedback monitor) — separate deferred issue per plan
