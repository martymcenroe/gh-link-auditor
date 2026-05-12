# Implementation Report: #148 Snooze key in HITL + recheck queue + ghla recheck command

## Summary

Added snooze/recheck functionality across four areas: N4 HITL review prompt, unified database schema/methods, CLI recheck command, and comprehensive tests.

## Changes

### 1. N4 Human Review (`src/gh_link_auditor/pipeline/nodes/n4_human_review.py`)
- Added `_SNOOZE = "snooze"` sentinel alongside existing `_EXIT` and `_SKIP`
- Updated prompt text: `[a]pprove / [r]eject / [s]kip / snoo[z]e / e[x]it:`
- Added `z` and `snooze` input handling in `prompt_user_approval()`
- Added `_snooze_to_db()` helper that opens UnifiedDatabase via `state["db_path"]` and writes a recheck queue entry
- When user chooses snooze: verdict is marked `approved=False`, and `_snooze_to_db()` is called to persist the snooze

### 2. Schema v3 Migration (`src/gh_link_auditor/unified_db.py`)
- Bumped `SCHEMA_VERSION` from 2 to 3
- Updated `recheck_queue` table definition to include: `url`, `repo_full_name`, `source_file`, `recheck_count`, `last_status`, `last_checked_at`
- Added `_migrate_v2_to_v3()` method using `PRAGMA table_info(recheck_queue)` to safely add columns only if missing
- Updated `_migrate()` to chain v1->v2->v3 migrations

### 3. UnifiedDatabase Methods (`src/gh_link_auditor/unified_db.py`)
- `snooze_finding(url, repo_full_name, source_file, snooze_days=7, reason=None)` -> int
- `get_due_rechecks()` -> list of dicts where `snooze_until < now` and status is not resolved/confirmed_dead
- `complete_recheck(recheck_id, new_status)` -> marks entry resolved or confirmed_dead
- `increment_recheck(recheck_id, snooze_days=7)` -> increments count, re-snoozes
- `get_recheck_stats()` -> dict with pending/resolved/confirmed_dead counts

### 4. StateDatabase Facade (`src/gh_link_auditor/state_db.py`)
- Bumped `StateDatabase.SCHEMA_VERSION` from 2 to 3 to match UnifiedDatabase

### 5. CLI Recheck Command (`src/gh_link_auditor/cli/recheck_cmd.py`)
- New `ghla recheck` subcommand with `--db-path` and `--dry-run` options
- Wired into `cli/main.py` via `build_recheck_parser`
- Logic: queries due rechecks, checks each URL via `network.check_url()`, updates status:
  - Live (status ok, code < 400) -> resolved
  - Dead + recheck_count >= 2 -> confirmed_dead
  - Dead + recheck_count < 2 -> increment count, re-snooze 7 days
- Prints per-entry results and summary with queue stats

## Design Decisions

- Snooze writes to recheck_queue independently of findings table (no finding_id required from HITL context)
- Used `_check_url()` wrapper in recheck_cmd.py for clean test patching
- Migration uses PRAGMA table_info to be idempotent (safe for fresh v3 installs)
- `_snooze_to_db()` catches all exceptions to never crash the HITL review flow
