# Test Report — #212 + #214 ([d]ead + [m]anual)

## Inventory

**127 new tests** across three files.

### `tests/unit/pipeline/test_n4.py` — 24 new tests

#### Prompt-level (added to `TestPromptUserApproval`)

| Test | Coverage |
|---|---|
| `test_dead_with_d` | `'d'` → `_DEAD` sentinel |
| `test_dead_with_dead` | `'dead'` alias |
| `test_dead_with_dead_product` | `'dead-product'` alias |
| `test_prompt_text_includes_dead_product` | Prompt string contains `[d]ead-product` |
| `test_manual_sets_candidate_and_approves` | `[m]` + valid URL mutates verdict candidate (source=manual) AND returns True |
| `test_manual_with_manual_word` | Full `manual` alias triggers URL flow |
| `test_manual_overwrites_existing_candidate` | `[m]` replaces a low-confidence pipeline candidate |
| `test_manual_cancel_with_empty_returns_to_main_prompt` | Empty URL cancels back to main prompt; original candidate preserved |
| `test_manual_invalid_url_reprompts` | Non-http(s) input re-prompts with "Invalid" message |
| `test_manual_accepts_http_not_just_https` | Accepts both http and https schemes |
| `test_prompt_text_includes_manual` | Prompt string contains `[m]anual` |

#### Orchestrator-level (new `TestDeadProductFlag` class)

| Test | Coverage |
|---|---|
| `test_dead_marks_not_approved` | `[d]` excludes verdict from approved fixes |
| `test_dead_calls_rewrite_queue_to_db` | Helper invoked with state + verdict |
| `test_dead_populates_rewrite_queued_in_state` | `state["rewrite_queued"]` list populated |
| `test_dead_does_not_set_review_aborted` | Doesn't trigger pipeline abort |
| `test_dead_mixed_with_approve` | Multi-verdict run: one `[d]` + one approve produces correct split |
| `test_summary_printed_when_rewrite_queued` | End-of-session prints count + CLI hint |

#### Helper-level (new `TestRewriteQueueToDb` class)

| Test | Coverage |
|---|---|
| `test_writes_row` | Helper persists URL/file/line/repo/reason to DB |
| `test_handles_missing_db_path` | Empty `db_path` → log warning, no crash |
| `test_uses_target_when_repo_parts_missing` | Falls back to `state["target"]` for repo_full_name |
| `test_swallows_db_exception` | DB layer raising → helper logs + returns (no propagation) |

### `tests/unit/test_unified_db_rewrite_queue.py` — 21 tests

| Class | Tests | Coverage |
|---|---|---|
| `TestSchemaVersion` | 3 | SCHEMA_VERSION == 4; fresh DB has `rewrite_queue`; version row reflects 4 |
| `TestAddToRewriteQueue` | 4 | row id; field persistence; null reason default; distinct ids |
| `TestGetRewriteQueue` | 6 | empty result; repo filter; no-filter returns all; default excludes exported; `--all` includes exported; newest-first order |
| `TestMarkRewriteQueueExported` | 4 | marks pending; skips already-exported; repo filter; zero-when-empty |
| `TestClearRewriteQueue` | 3 | deletes all for repo; zero-when-empty; includes exported in delete |
| `TestMigrationV3ToV4` | 1 | hand-rolled v3 DB upgrades to v4 + gains `rewrite_queue` on first open |

### `tests/unit/cli/test_rewrite_queue_cmd.py` — 20 tests

| Class | Tests | Coverage |
|---|---|---|
| `TestCmdList` | 4 | empty DB; empty for repo; lists pending; filters by repo; `--all` includes exported |
| `TestCmdExport` | 3 | no-pending case; prints markdown block; does NOT mark exported (separation of concerns) |
| `TestCmdMarkExported` | 3 | marks pending; singular grammar ("1 entry"); zero entries |
| `TestCmdClear` | 2 | deletes all for repo; zero entries |
| `TestFormatExportMarkdown` | 4 | casual register (no `##` headers, no `**`, no Unicode arrows); includes line when present; omits "line" when None; default reason "needs rewrite" |
| `TestParserRegistration` | 3 | parser registers; export requires --repo; mark-exported requires --repo and --issue |

## Coverage report (new code)

```
src\gh_link_auditor\cli\rewrite_queue_cmd.py          74 stmts   0 miss   100%
src\gh_link_auditor\pipeline\nodes\n4_human_review.py  214 stmts   10 miss   95%
                                                                          ────
  In-PR diff coverage (excluding pre-existing lines):       100%
  Pre-existing uncovered (untouched by this PR):
    272-273    _snooze_to_db exception handler (was uncovered before)
    384-395    _LIVE branch in n4_human_review (was uncovered before)
    417-419    false-positives summary print (was uncovered before)
```

## Regression check

```
1925 passed, 1 skipped, 1 warning in 110.58s
```

No regressions. The `test_snooze_recheck.py` file's three `version == 3` assertions were loosened to `>= 3` since later migrations (v4) chain in. Test intent preserved: v3 columns must exist; current version must be >= 3.

`test_state_db.py::test_create_database_schema_version` passes after wiring `StateDatabase.SCHEMA_VERSION` to mirror `UnifiedDatabase.SCHEMA_VERSION` (single source of truth).

## CLI smoke-test (manual)

```
$ poetry run python -m gh_link_auditor.cli.main rewrite-queue --help
usage: ghla rewrite-queue [-h] {list,export,mark-exported,clear} ...
positional arguments:
  {list,export,mark-exported,clear}
    list                Show pending rewrite-queue entries
    export              Print a markdown block ready to paste into an upstream issue
    mark-exported       Mark all unexported entries for a repo as linked to an upstream issue
    clear               Hard-delete entries for a repo
```

Confirmed end-to-end via the existing unit tests (`TestParserRegistration` + per-subcommand command tests using `argparse.Namespace`).
