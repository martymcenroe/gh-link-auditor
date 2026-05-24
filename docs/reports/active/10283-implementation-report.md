# 10283 - Implementation Report

**Issues:** #283 (scaffold), #285 (cache tables), #286 (report format), #287 (subagent infra)
**Branch:** `283-preflight-infra-bundle`
**Umbrella:** #281

## Summary

PR-β: the infrastructure bundle. Lands the four interdependent infra pieces so subsequent gate / score PRs have a complete plug-in surface:

1. **`tools/preflight_check.py`** scaffold (#283) — empty-shell CLI + `run_preflight()` entry point that returns `PASS` with no evaluations. Gate / score dispatch lands per-issue under #281.
2. **3 new preflight cache tables in `unified_db`** + schema v8→v9 migration (#285). Existing `cache_url_check(ttl_hours=...)` API was already preflight-ready; no extension needed there.
3. **Markdown + JSON report renderers** (#286), plus `save_report(report, log_dir)` helper. Operator-clickable links, hard-gate evidence table, score-breakdown table, OPERATOR REVIEW NEEDED banner, SKIP-PREFLIGHT banner.
4. **`src/gh_link_auditor/preflight/subagent.py`** with `RealSubagent` (subprocess `claude --print` with `CLAUDECODE=""` per universal CLAUDE.md mandate), `SubagentVerdict` enum, `FakeSubagent` fake (no MagicMock), 3 prompt files under `prompts/preflight/`, `ANTI_AI_PHRASES` keyword fallback when `claude` CLI is unavailable.

No gates or scores fire yet — the dispatch surface exists and `run_preflight()` returns `PASS` for every candidate.

## Files

### New (production)
- `src/gh_link_auditor/preflight/__init__.py` — public re-exports
- `src/gh_link_auditor/preflight/subagent.py` — `RealSubagent` + `SubagentVerdict` + `anti_ai_keyword_fallback` + `_parse_verdict_token`
- `src/gh_link_auditor/preflight/report.py` — `PreflightVerdict` + dataclasses + `render_markdown` + `render_json` + `save_report`
- `tools/preflight_check.py` — CLI scaffold with `run_preflight` stub + 6 flags
- `prompts/preflight/ai_scan.txt` — gate #1 subagent prompt (returns `clean | uncertain | hostile`)
- `prompts/preflight/content_equiv.txt` — score C5 subagent prompt (returns `clean | partial | unrelated`)
- `prompts/preflight/redirect_target.txt` — gate #7 subagent prompt (returns `clean | unrelated`)
- `data/preflight-reports/.gitkeep` — gitignored output dir

### New (tests)
- `tests/fakes/subagent.py` — `FakeSubagent` (records calls, returns canned verdicts, per-prompt overrides)
- `tests/unit/preflight/test_report.py` — 12 tests for `PreflightVerdict` / dataclass / `render_markdown` / `render_json` / `save_report`
- `tests/unit/preflight/test_subagent.py` — 22 tests for `_parse_verdict_token` / `anti_ai_keyword_fallback` / `RealSubagent` / `FakeSubagent`
- `tests/unit/tools/test_preflight_check.py` — 13 tests for `_build_parser` / `_make_run_id` / `run_preflight` scaffold / `main` CLI

### Modified
- `src/gh_link_auditor/unified_db.py` — `SCHEMA_VERSION = 9`; 3 new tables in `_create_all_tables`; `_migrate_v8_to_v9` (narrow — adds only the 3 new tables explicitly so Windows test cleanup isn't tripped by extra DB activity); 6 new API methods (`cache_pr_stats` / `get_cached_pr_stats` / `cache_repo_meta` / `get_cached_repo_meta` / `cache_ai_scan` / `get_cached_ai_scan`)
- `tests/unit/test_unified_db.py` — `TestPreflightCaches` class (12 tests for the 3 new caches) + `TestMigrationV8ToV9` (2 tests for migration idempotency)
- `tests/unit/bulk_scan/test_storage.py` — `TestSchemaV7::test_schema_version` updated to assert `SCHEMA_VERSION == 9` (was 8)
- `.gitignore` — `data/preflight-reports/*` ignored, `!data/preflight-reports/.gitkeep` kept

## Subagent invocation: `claude --print` instead of Agent tool

Per universal `C:\Users\mcwiz\Projects\CLAUDE.md`:

> NEVER use `@anthropic-ai/sdk` or ask for API keys. Use `claude --print` with `CLAUDECODE=""` env for all LLM calls. User has Max subscription.

`RealSubagent.run()` shells out to `claude --print "<rendered prompt + JSON context>"` with `CLAUDECODE=""` in the env, 60s timeout. Timeout → `UNCERTAIN`. Non-zero exit → `UNCERTAIN`. Missing `claude` binary → `UNCERTAIN`. Anything that isn't one of the 5 valid tokens (`clean | uncertain | hostile | partial | unrelated`) on the first line → `UNCERTAIN`.

Fallback `anti_ai_keyword_fallback` uses the existing `hostile_classifier.ANTI_AI_PHRASES` list — hits → `UNCERTAIN`, clean → `CLEAN`. Subsequent PRs (gate #1 / #288) plug the fallback in.

## Migration discipline

`_migrate_v8_to_v9` explicitly issues only the 3 new `CREATE TABLE IF NOT EXISTS` statements rather than re-calling `_create_all_tables`. The narrower scope keeps Windows tempdir cleanup races (`TestMigrationV2ToV3`) from tripping on the longer migration chain. Pattern documented inline in the method.

## Verification

| Check | Result |
|---|---|
| `poetry run pytest -q` | 2315 passed, 1 skipped (was 2247 after PR-α; +68 from PR-β) |
| `poetry run ruff format --check .` | 242 files already formatted |
| `poetry run ruff check .` | All checks passed |
| `git grep -i -E '(A\+\+\|PRs filed\|contribution graph\|green square\|naked ambition)'` | 0 hits (Phase A clean) |
| `poetry run python tools/preflight_check.py --repo owner/r` | exits 0; prints `verdict=pass score=0 threshold=90` |
| `poetry run python tools/preflight_check.py --repo owner/r --report --preflight-log-dir /tmp/x` | writes markdown + JSON to /tmp/x |

## Out of scope (subsequent PRs)

- Tool A integration with the preflight gate — PR-γ (#284)
- 10 hard gates implementations — PR-δ + PR-ε
- 12 score components — PR-η + PR-θ
- Recorded fixtures + live + golden tests — PR-ι
- Operator-escalation report header refinements — PR-ι (#313)
- End-to-end verification — operator gate (#314)
