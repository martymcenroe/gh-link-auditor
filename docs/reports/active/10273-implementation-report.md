# Implementation Report: #273 derive_replacement_prs.py

## Summary

The bulk-scan pipeline (`ghla bulk-scan start`) produces `derived_candidate` rows in `bulk_scan_findings`. The per-target pipeline (`ghla batch run`) submits PRs via N6. Until now there was no bridge between them — 157 candidates were stuck in the DB with no automated path to PR.

This PR ships `tools/derive_replacement_prs.py`: reads unsurfaced derived-candidate rows, groups them by source repo, and calls `n6_submit_pr` directly with synthesized PipelineState. Each repo's candidates bundle into a single PR.

See LLD-273.

## What it does

```
poetry run python tools/derive_replacement_prs.py [flags]
```

| Flag | Effect |
|------|--------|
| `--db PATH` | DB path (default `~/.ghla/ghla.db`) |
| `--run-id X` | restrict to one bulk-scan run |
| `--method M` | filter by candidate method (`github_api_redirect`, `url_mutation`, `wikipedia_suggest`, ...) |
| `--min-confidence N` | filter by confidence floor |
| `--repo owner/name` | single-repo filter (debug) |
| `--max-prs N` | safety cap (default 10) |
| `--auto-approve` | skip per-repo confirmation |
| `--dry-run` | preview without forking |

Default behavior: per-repo preview + `[y/n/s]` prompt. `[s]` stops the run cleanly (already-submitted work retained).

## Flow

1. `SELECT * FROM bulk_scan_findings WHERE investigation_state='derived_candidate' AND surfaced=0` + optional filters
2. Group by `repo_full_name` (the source repo whose doc references the dead URL)
3. For each group:
   - Skip if `udb.is_blacklisted(repo_url)` (#150 hostility logic)
   - Skip if `pr_outcomes` already has an `open` PR for this repo (no dupes)
   - Build `FixPatch` list + `Verdict` list (for PR body context)
   - Build a synthetic `PipelineState` with `target_type='url'`, fixes, verdicts, db_path
   - Call `n6_submit_pr(state)` — fork via classic-PAT, clone, str-replace, commit, push, cross-fork PR
   - On `pr_url` set: `INSERT INTO pr_outcomes`, `UPDATE bulk_scan_findings SET surfaced=1` for all rows in this repo
   - On error: log to summary, leave rows as `surfaced=0` (idempotent retry)
4. Print summary (submitted / skipped / errors)

## Files

| File | Change |
|------|--------|
| `tools/derive_replacement_prs.py` | NEW (~280 LoC) |
| `tests/unit/tools/test_derive_replacement_prs.py` | NEW (45 tests) |
| `docs/lld/active/LLD-273.md` | NEW design |

## Reuse vs. new code

- **Reuses** `n6_submit_pr` end-to-end (fork+commit+PR via classic-PAT)
- **Reuses** `update_trust_on_submit` (called by N6 internally)
- **Reuses** `udb.is_blacklisted` (#150 logic) for the skip check
- **Reuses** `udb.record_pr_outcome` to write to `pr_outcomes` table
- **New** code: row→FixPatch / row→Verdict translators, the orchestration loop, the preview/prompt UI, the surfaced=1 update

## Test count

- 45 new tests in `tests/unit/tools/test_derive_replacement_prs.py`
- Full suite: **2203 passed, 1 skipped** (+45 net)

## Coverage

`tools/derive_replacement_prs.py`: **99%** (175/176 statements). The single uncovered line is the `if __name__ == "__main__": sys.exit(main())` guard at the bottom — structurally untestable from a unit test.

Test surface:

| Class | Tests | Covers |
|---|---:|---|
| `TestRowToFix` | 1 | Row→FixPatch translation |
| `TestRowToVerdict` | 5 | Row→Verdict + NULL handling |
| `TestGroupByRepo` | 2 | Repo grouping |
| `TestBuildState` | 2 | PipelineState synthesis |
| `TestLoadUnsurfacedCandidates` | 6 | Filter logic (surfaced, state, run_id, method, confidence, repo) |
| `TestMarkSurfaced` | 2 | Update + empty-list edge case |
| `TestHasOpenPr` | 3 | No PR / open / closed |
| `TestPromptYesNoStop` | 5 | y/n/s/full-word/invalid-reprompt |
| `TestDeriveAndSubmit` | 10 | End-to-end with fake N6 — blacklist skip, dup-PR skip, n6 error, n6 exception, max_prs cap, dry-run, interactive decline/stop, no-pr-url path |
| `TestShowPreview` | 3 | Preview rendering + NULL-meta path |
| `TestPrintSummary` | 2 | Summary with/without errors |
| `TestBuildParser` | 2 | Defaults + all flags |
| `TestMain` | 2 | Dry-run main + empty DB |
| **Total** | **45** | |

All end-to-end tests use a fake `n6_fn` so no real network/forking happens.

## Out of scope

- Removal-PR derivation (truly-dead URLs the pipeline cannot fix). Separate tool, separate issue. The handoff's `derive_removal_prs.py` is this tool's counterpart.
- Concurrent submission across repos. Sequential for v1. Can parallelize later if quota allows and Cerberus auto-review keeps up.
- CLI integration into `ghla` subcommands. Tool lives in `tools/` per the existing pattern.
- Trust-tier gating of tier-2 candidates. N6's existing `update_trust_on_submit` runs as-is; tier-2 filtering would be a future enhancement.
- Reusing a single fork branch across multiple invocations. Each PR uses N6's default `fix/dead-links` branch on a fresh clone.
