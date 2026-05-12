# Implementation Report: #150 Automated Maintainer Blacklisting

## Changes

### pr_tracker.py
- Added auto-blacklist on "fix stolen" (maintainer committed fix directly → permanent blacklist, source=fix_stolen)
- Added 30-day unresponsive timeout (PR open >30 days → 90-day expiry blacklist, source=unresponsive)
- Deduplication: checks `is_blacklisted()` before adding unresponsive entry
- Opens `UnifiedDatabase` alongside `MetricsCollector` for blacklist writes

### n0_load_target.py
- Added blacklist check before scanning URL targets
- If blacklisted, appends error and returns early (no doc files, no API calls)

### unified_db.py
- Added `get_blacklist_by_source()` method for stats grouping

### cli/blacklist_cmd.py (NEW)
- `ghla blacklist list` — show active entries with source, reason, expiry
- `ghla blacklist add <url>` — manual blacklist
- `ghla blacklist remove <id>` — remove entry
- `ghla blacklist stats` — count by source

### cli/main.py
- Wired `build_blacklist_parser` into CLI

## Decisions
- Unresponsive expiry set to 90 days (3x the detection threshold)
- No hostile comment detection in this PR — deferred to follow-up
- Blacklist check in N0 only for URL targets (local targets have no repo to blacklist)
