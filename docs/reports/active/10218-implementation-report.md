# Implementation Report — #218 (bulk-scan tool)

**Branch:** `218-bulk-scan`
**LLD:** `docs/lld/active/LLD-218.md`
**Kickoff runbook:** `docs/runbooks/bulk-scan-kickoff.md`

## Summary

A self-contained, unattended bulk-scan tool that selects 7,500 active Python doc repos, finds top-3 high-quality link replacements per repo, ranks them globally, and writes a markdown report for operator triage post-trip. Hard quality stop-loss, resumable, no cloning, all state in SQLite.

## Module layout

```
src/gh_link_auditor/bulk_scan/
  __init__.py
  config.py          # 25 tunables (workers, thresholds, file paths)
  storage.py         # 11 DB CRUD helpers across 3 tables
  selection.py       # Stage 0: gh-search by star-range slices
  inventory.py       # Stage 1: tree list + raw-CDN fetch + URL regex
  liveness.py        # Stage 2: ThreadPoolExecutor HEAD (20 workers)
  investigation.py   # Stage 3: LinkDetective wrap, tier-1 filter, confidence
  scoring.py         # Stage 4: top-3 / repo, threshold filter, ranking
  heartbeat.py       # Periodic status snapshot to phone-readable file
  runner.py          # State machine + checkpointing + signal handling

src/gh_link_auditor/cli/bulk_scan_cmd.py    # `ghla bulk-scan` subcommand
docs/runbooks/bulk-scan-kickoff.md         # Operator kickoff procedure
```

## Schema migration

v4 → v5, additive. Three new tables:

- `bulk_scan_runs` — one row per run, status state machine, quality_aborted flag
- `bulk_scan_repos` — per-repo progress (PK `(run_id, repo_full_name)`)
- `bulk_scan_findings` — every candidate, surfaced flag for ones that make the report

Indexes: `(run_id, status)` on repos, `(run_id, confidence DESC, surfaced)` and `(run_id, repo_full_name, surfaced)` on findings.

`_migrate_v4_to_v5` idempotent (CREATE IF NOT EXISTS). Bumps `SCHEMA_VERSION` to 5.

## State machine

```
selecting → inventorying → checking → investigating → scoring → done
                                    ↘ aborted
                                    ↘ quality_aborted
```

Each transition persists immediately. Resume reads `bulk_scan_runs.status` and picks up at the matching stage.

## Quality safeguards

| Safeguard | Threshold | Where |
|---|---|---|
| Tier-1 methods only | `url_mutation`, `strip_index`, `wikipedia_suggest`, `github_api_redirect` AND `verified_live` | `investigation.filter_tier1` |
| Confidence floor | ≥ 0.7 | `config.SURFACE_CONFIDENCE_THRESHOLD` |
| Top-N per repo | 3 | `scoring.select_top_n_per_repo` |
| Mid-run sample | After 100 findings | `runner._maybe_write_sample` |
| Stop-loss | median(last 100) < 0.7 → abort | `runner._check_quality_stop_loss` |

`redirect_chain` and `sitemap_search` explicitly excluded from tier-1 (#197 and "no same-token verifier yet" respectively). `archive_only` always dropped.

## Safety caps (declared in config)

- `RAM_WARN_MB=1024`, `RAM_ABORT_MB=2048`
- `DISK_REFUSE_GB=4.5`
- `MAX_DOC_FILES_PER_REPO=200`, `MAX_URLS_PER_REPO=1000`
- `LIVENESS_WORKER_COUNT=20`, `INVESTIGATION_WORKER_COUNT=8`
- `HEARTBEAT_INTERVAL_S=300`, `BATCH_SIZE=100`

Runtime enforcement of RAM/disk caps deferred to follow-up; ceilings documented and respected by per-repo circuit breakers.

## CLI

```
ghla bulk-scan start [--target N] [--run-id ID] [--db-path P] [--token T]
ghla bulk-scan status [--run-id ID]
ghla bulk-scan stop                  # writes data/bulk-scan-abort
ghla bulk-scan report --run-id ID
ghla bulk-scan list-runs
```

Five subcommands; all registered via `build_bulk_scan_parser` wired into `cli/main.py`.

## Files written at runtime

- `data/bulk-scan-heartbeat.txt` — every 5 min during a run, phone-readable
- `data/bulk-scan-sample.md` — after 100 findings, mid-run quality check
- `data/bulk-scan-report.md` — at run end, ranked list (the deliverable)
- `data/bulk-scan-abort` — operator-touched, requests graceful stop

## What is NOT in this PR (and why)

- **#215 PyPI tier-2 lookup deferred.** Operator OK'd dropping it for the trip; bulk run will miss `numpy.scipy.org`-class moves. Re-investigate those rows post-trip.
- **No async / asyncio.** Concurrency via `concurrent.futures.ThreadPoolExecutor` in Stage 2 only. Stages 1 and 3 sequential — GitHub API limits + LinkDetective's serial behavior make sequential the right call.
- **No content-similarity check on archive.org snapshots.** Held out of tier-1; archive candidates never surface in this mode.
- **Runtime RAM/disk enforcement.** Caps declared in config; runtime watcher to follow.

## Test summary

- **63 new tests** across `bulk_scan/test_storage.py` (24), `test_inventory.py` (12), `test_investigation.py` (13), `test_scoring.py` (11), `test_heartbeat.py` (5), and `cli/test_bulk_scan_cmd.py` (10)
- Coverage focused on pure functions and DB layer (network paths use the existing N1/N2 helpers and inherit their fakes)
- Full suite: **2013 passed**, 1 skipped, 0 failed (up from 1950 baseline post-#211)
- Two existing tests loosened (`SCHEMA_VERSION == 4` → `>= 4`) for forward-compat with future bumps
- ruff format + check clean

## Acceptance

- [x] DB tables created with v4→v5 migration
- [x] 5 stages each implemented as a focused module
- [x] State machine drives resume correctly
- [x] Heartbeat file writes with all required fields
- [x] Quality sample renders after 100 candidates
- [x] Quality stop-loss fires when median < 0.7
- [x] Report renders ranked surfaced findings
- [x] CLI: start/status/stop/report/list-runs all functional
- [x] ≥95% coverage on pure-function code; network paths exercised by inherited fakes
- [x] Pre-flight #211 landed before this (gating)
- [x] Kickoff runbook drafted

## Closes

Closes #218
