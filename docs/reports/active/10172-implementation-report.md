# Implementation Report: #172 Archive Shipped LLDs/Reports

## Summary

Audit on 2026-05-12 found three doc trees holding artifacts whose tracking issues had long since closed. This PR moves them to their respective archive directories.

## Changes

### `docs/lld/`
- Created `docs/lld/archived/`.
- Moved 14 LLDs (`LLD-001`, `LLD-002`, `LLD-003`, `LLD-004`, `LLD-005`, `LLD-009`, `LLD-010`, `LLD-011`, `LLD-019`, `LLD-020`, `LLD-021`, `LLD-022`, `LLD-036`, `LLD-067`) from `active/` to `archived/`. Every one maps to a closed issue.

### `docs/reports/`
- Created `docs/reports/archived/`.
- Moved 22 reports from `active/` to `archived/`: 10 closed-issue pairs (impl + test) for #2, #3, #20, #21, #22, #36, #67, #148, #149, #150, plus two pre-numbering-scheme files (`9-`, `11-`).

### `docs/lineage/`
- Moved 16 lineage directories from `active/` to `done/` (the existing convention in this tree): `1-lld`, `2-lld`, `3-lld`, `4-lld`, `5-lld`, `9-lld`, `10-lld`, `11-lld`, `19-lld`, `19-lld-n1`, `20-lld`, `21-lld`, `22-lld`, `5-testing`, `9-testing`, `11-testing`. All map to closed issues.

### Local config (NOT in this PR, no PR landing)
- `.unleashed.json` (untracked file) had its deprecated `onboard.pickupThresholdMinutes` field removed locally. The field is ignored by the current event-ordered pickup system.

## Out of Scope

- The empty `.claude/worktrees/agent-a1e3c229/` directory on disk: removed from git's worktree registry along with two siblings as part of the audit, but Windows holds a process handle on the empty dir. Harmless; expected to clear on next reboot.
- Sibling worktree `../gh-link-auditor-158` (from issue #158, March): leftover from previous work. Not removed in this PR — out of audit scope for #172.

## Files Changed

170 git renames staged. No code or test changes.
