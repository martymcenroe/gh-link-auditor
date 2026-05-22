# 10231 Implementation Report

**Issue:** #231
**Branch:** `231-reject-unknown-runid`

## Changes

| File | Change |
|---|---|
| `src/gh_link_auditor/cli/bulk_scan_cmd.py` | Added `--new-run` flag to `start` subparser. New `_suggest_run_ids()` helper. `_cmd_start` gates: unknown id + no `--new-run` → exit 2 with "Did you mean" suggestions; existing id + `--new-run` → exit 2 (avoid clobber). |
| `tests/unit/cli/test_bulk_scan_cmd.py` | 10 new tests: 6 for the gate matrix, 4 for the suggestion helper. |
| `docs/lld/active/LLD-231.md` | New LLD. |

## Flag matrix

| `--run-id` | `--new-run` | id in DB | Behavior |
|---|---|---|---|
| not given | n/a | n/a | auto-generate timestamp id, create + run (unchanged) |
| given | not set | yes | resume (unchanged) |
| given | not set | **no** | **exit 2** with "not found" + "Did you mean" suggestions |
| given | set | yes | **exit 2** with "already exists" |
| given | set | no | create + run |

The bidirectional foot-gun protection (rejecting `--new-run` on existing id) means the operator can't accidentally start a new run under the name of an existing one.

## Verification

- 20/20 targeted tests pass
- `ruff check` + `ruff format`: clean
