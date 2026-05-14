# Implementation Report — #212 + #214 (HITL: [d]ead-product + [m]anual)

**Branch:** `212-dead-flag`
**LLD:** `docs/lld/active/LLD-212.md`
**Bundled:** #212 (rewrite queue) + #214 ([m]anual URL entry) — single-letter prompt additions in the same module, shipped together.

## Summary

Two new operator keys at the N4 HITL prompt:

- `[d]ead-product` — verdict excluded from this PR's fixes AND persisted to a new `rewrite_queue` table for later batching into an upstream content-rewrite issue.
- `[m]anual` — operator types in a replacement URL; mutates the verdict's candidate (`source="manual"`), approves it for the PR.

Plus a CLI surface (`ghla rewrite-queue list/export/mark-exported/clear`) for managing the queue.

## Changes

| Area | Files | Action |
|---|---|---|
| Schema | `src/gh_link_auditor/unified_db.py` | Bump `SCHEMA_VERSION` 3 → 4; add `rewrite_queue` table; add `_migrate_v3_to_v4`; add 4 public methods (`add_to_rewrite_queue`, `get_rewrite_queue`, `mark_rewrite_queue_exported`, `clear_rewrite_queue`). |
| Schema facade | `src/gh_link_auditor/state_db.py` | `StateDatabase.SCHEMA_VERSION` now mirrors `UnifiedDatabase.SCHEMA_VERSION` (avoid hardcoded drift). |
| HITL prompt | `src/gh_link_auditor/pipeline/nodes/n4_human_review.py` | Add `_DEAD` sentinel, `_prompt_replacement_url()` helper, `[d]`/`[m]` matchers, `_rewrite_queue_to_db()` helper. New `rewrite_queued` session list + end-of-session summary. Updated prompt string. |
| CLI | `src/gh_link_auditor/cli/rewrite_queue_cmd.py` (new) | 4 subcommands; markdown-export rendered in Draft-A casual register (#209 alignment). |
| CLI wiring | `src/gh_link_auditor/cli/main.py` | Register `build_rewrite_queue_parser`. |
| Tests | `tests/unit/pipeline/test_n4.py`, `tests/unit/test_unified_db_rewrite_queue.py` (new), `tests/unit/cli/test_rewrite_queue_cmd.py` (new), `tests/unit/test_snooze_recheck.py` | +127 new tests; loosened 3 hardcoded `version == 3` assertions to `>= 3`. |
| Docs | `docs/lld/active/LLD-212.md` | New (bundled spec for #212 + #214). |

## Schema migration

v3 → v4 is purely additive: one new table (`rewrite_queue`), one index. Existing rows in any table untouched. Migration is idempotent (`CREATE TABLE IF NOT EXISTS`).

Test `TestMigrationV3ToV4::test_v3_db_gains_rewrite_queue` confirms a hand-rolled v3 DB upgrades cleanly on first open.

## Prompt UX

**Before:**
```
[a]pprove / [r]eject / [s]kip / snoo[z]e / [l]ive / [g]oogle / e[x]it:
```

**After:**
```
[a]pprove / [r]eject / [m]anual / [s]kip / snoo[z]e / [l]ive / [d]ead-product / [g]oogle / e[x]it:
```

`[m]` slotted next to `[r]` because they are the two most likely choices when the pipeline shows "no candidate" — either ship the URL you know, or skip.

`[d]ead-product` slotted next to `[l]ive` because both are "operator-observation labels" (vs. the immediate-decision options like a/r/m).

### `[m]anual` URL entry flow

```
... press 'm' ...
  Replacement URL (or Enter to cancel): https://numpy.org/
```

- Empty input → cancel, back to main option prompt without losing state
- Invalid URL (not http/https) → "Invalid — must start with http:// or https://", re-prompt for URL
- Valid URL → mutate `verdict["candidate"]` to `{url: <input>, source: "manual"}`, return True (approve)

Trust system treats `source="manual"` as a tier-1 vouched URL (operator confirms).

### `[d]ead-product` flow

```
... press 'd' ...
  → queued for deeper rewrite: https://www.enthought.com/product/canopy/
```

- Verdict marked `approved=False` (same as reject — excluded from fixes)
- Row inserted into `rewrite_queue` with reason `"dead product / section needs rewrite"`
- End-of-session summary prints pending count and recommends `ghla rewrite-queue export`

## Test summary

- 127 new tests across 3 files; all green
- Full suite: **1925 passed**, 1 skipped, 0 failed (was 1842 baseline at session start, now up via #209 + #212)
- New-code coverage:
  - `cli/rewrite_queue_cmd.py`: **100%** (74/74)
  - `pipeline/nodes/n4_human_review.py`: **97%** (lines 384-395 and 417-419 are pre-existing untested `[l]ive` and false-positives-summary code; new code in this PR all covered)
  - DB methods: 100% via the new `test_unified_db_rewrite_queue.py`

## Risk

1. **Schema bump affects every consumer.** Tested with the existing snooze/recheck migration tests (loosened to `>= 3`). A v1 or v2 DB will run the full v1→v2→v3→v4 chain on first open — exercised in CI.
2. **Mutating `verdict["candidate"]` in `prompt_user_approval` is a new side-effect.** Existing callers (test fixtures and `n4_human_review`) treat verdicts as opaque dicts and only inspect `approved` / `candidate` after — verified by full suite.
3. **`[m]anual` URL validation is intentionally minimal** (http/https prefix only). No DNS check, no HEAD verification. Trade-off: operator types fast; downstream Slant/N6 catches truly broken inputs. Can tighten in a follow-up if false-typed URLs become a problem.
4. **Markdown export uses Draft-A casual register** (#209 alignment): lowercase, no headings, no bold, no Unicode arrows. Consistent with the no-AI-tell PR-body voice.

## Acceptance checklist

- [x] `rewrite_queue` table created on fresh DB
- [x] v3 DB auto-migrates to v4 on first open
- [x] 4 DB methods with 100% coverage
- [x] `[d]ead-product` available at N4 prompt; pressing `d` excludes from fixes AND writes row
- [x] `[m]anual` available at N4 prompt; pressing `m` enters URL flow with validation + cancel
- [x] End-of-session summary prints rewrite count + export hint
- [x] `ghla rewrite-queue list/export/mark-exported/clear` works end-to-end
- [x] Full suite green (1925 passed)
- [x] ≥95% coverage on new code (cli: 100%, n4 changed surface: 100% — pre-existing untested lines unchanged)
- [x] Ruff format + check clean

## Out-of-scope follow-ups

- Sidecar `data/python-guide-rewrite-queue.md` entries (Canopy x2, Komodo) NOT migrated by this PR. Next session can run `ghla rewrite-queue add` (TODO) or hand-insert.
- Per-line annotation when multiple URLs share a section — currently one row per (url, file, line). Acceptable noise for now.
