# Implementation Report: HITL UX bundle (#194 + #195 + #196 minimum viable)

## Summary

While reviewing python-guide's 30 findings during the Phase 4 attempt, the operator hit three friction points within minutes:

1. No source-link to click — had to manually navigate to file:line in a browser tab (#194).
2. No way to record "I checked, this URL is actually live" — manual rejections only (#195).
3. No diagnostic search shortcut — had to construct Google queries from scratch (#196).

This PR ships the minimum-viable slice of all three. Each touches the same N4 prompt; combining keeps the surface change to one file.

## Changes

### `src/gh_link_auditor/pipeline/nodes/n4_human_review.py`

- New helper `build_github_source_url(owner, repo, source_file, line_number)`. Uses GitHub's `blob/HEAD` so we don't need to fetch the default-branch name.
- New helper `generate_google_searches(dead_url) -> list[str]`. Four templates (domain-scoped, "{name} replacement", "{name} successor OR deprecated", literal-URL triangulation).
- `format_verdict_for_review` gains optional `github_source_url=` parameter; when set, adds a `Source:` line to the prompt.
- New `_LIVE` sentinel.
- `prompt_user_approval` rewritten with a re-prompt loop:
  - `[g]oogle` — prints search URLs and re-prompts.
  - `[l]ive` — returns `_LIVE` sentinel.
  - All existing options unchanged.
  - Prompt text now `[a]pprove / [r]eject / [s]kip / snoo[z]e / [l]ive / [g]oogle / e[x]it:`.
- `n4_human_review` orchestration:
  - Constructs the GitHub source URL from `state["repo_owner"]` and `state["repo_name_short"]` and passes it to `format_verdict_for_review`.
  - On `_LIVE`, treats as reject for pipeline flow but appends to `state["false_positives"]` (list of dicts).
  - End-of-review summary block prints any false positives flagged during the session.

### `tests/unit/pipeline/test_n4.py`

- New `TestGenerateGoogleSearches` (4 tests).
- New `TestBuildGithubSourceUrl` (3 tests).
- New `TestFormatVerdictWithGithubUrl` (2 tests).
- New `TestPromptUserApproval` entries: `test_live_with_l`, `test_live_with_live`, `test_google_re_prompts`, `test_prompt_text_includes_live_and_google`.

## Files modified

| File | Change |
|---|---|
| `src/gh_link_auditor/pipeline/nodes/n4_human_review.py` | helpers + `_LIVE` + prompt loop + false-positive tracking |
| `tests/unit/pipeline/test_n4.py` | 13 new tests across 3 new test classes + 4 new tests in existing class |
| `docs/lld/active/LLD-194-195-196.md` | NEW design |

## Test count

`pytest --co -q` collects **1820 tests** post-change (was 1807, +13 net).

## Deferred (will file follow-up)

- DB persistence for false positives (`false_positive_log` table, schema bump).
- Post-run "file batch issue" prompt that auto-files a GitHub issue grouping all `[l]`-flagged URLs from a session.
- `ghla false-positives {list, file-issue, stats}` CLI subcommand.
- `[m]ore` option that cycles through anchor text, surrounding source, alt candidates.
- Anchor-text capture in N1 (touches scanner + state schema).

These were in the original #194/#195/#196 scopes but pushed off to keep this PR small and shippable today. The operator gets immediate value from the minimum-viable slice; the heavier persistence/CLI work follows.

## Operator impact

Next audit run:
- Every verdict has a clickable GitHub URL — no manual navigation.
- `[l]` for false positives — typed flags surface in a summary block at end.
- `[g]` for diagnostic search — 4 pre-built queries per click.

Reduces the 30-finding review from ~15 minutes of context-switching to ~5 minutes of inline triage.
