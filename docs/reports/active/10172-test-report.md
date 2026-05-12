# Test Report: #172 Archive Shipped LLDs/Reports

## Verification

This PR moves files only — no code or test changes. Verification confirms the moves are correct and nothing depends on the old paths.

### Pre/post-move counts

| Tree | Before (active) | After (active) | After (archive) |
|------|----------------|----------------|-----------------|
| `docs/lld/` | 14 | 0 | 14 |
| `docs/reports/` | 22 | 2 (new for this PR) | 22 |
| `docs/lineage/` | 16 | 0 | 16 (in `done/`) |

The two files remaining in `docs/reports/active/` are this PR's own impl + test reports.

### Reference scan

`grep -rn "docs/(lld\|reports)/active"` against the post-move tree finds only:
- `CLAUDE.md` workflow rule that documents where *new* LLDs go (still correct).
- Two archived LLDs containing internal references to the active path at the time of writing — historical record, intentionally not rewritten.
- Three lineage drafts (now in `done/`) with the same historical references.

No code, CI workflow, or active doc points at the old paths. No broken references.

### Test suite

Test suite is currently unrunnable from the project venv (separate finding being addressed in #173). The 1,705 milestone from MEMORY.md cannot be verified in this session — but this PR is doc-only and cannot affect Python imports or test collection.

## Verdict

Move is safe. Nothing referenced the moved paths.
