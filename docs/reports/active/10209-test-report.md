# Test Report — #209 (Draft-A PR Body Generator)

## Test Inventory

`tests/unit/pipeline/test_pr_message.py` — 45 tests across 3 test classes:

### `TestGeneratePrTitleFromFixes` (7 tests)

| Test | What it verifies |
|---|---|
| `test_empty_list` | `[]` → `"fix broken docs links"` |
| `test_single_fix` | 1 fix → `"fix broken docs link"` |
| `test_multiple_fixes` | N fixes → `"fix {N} broken docs links"` |
| `test_no_conventional_prefix` | Never starts with `docs:`, `feat:`, or `chore:` |
| `test_lowercase_only` | Title is fully lowercase across all input regimes |
| `test_no_period` | No trailing period |
| `test_no_file_name_in_title` | File name never appears in title (it's body/diff content) |

### `TestFindVerdictForFix` (4 tests)

| Test | What it verifies |
|---|---|
| `test_finds_matching_verdict` | Returns the verdict whose dead_link URL and source_file match |
| `test_returns_none_when_no_url_match` | Different URL → None |
| `test_returns_none_when_no_file_match` | Different source_file → None |
| `test_empty_verdicts` | Empty list → None |

### `TestGeneratePrBodyFromFixes` (34 tests)

#### Exact-format tests (4)
| Test | What it verifies |
|---|---|
| `test_single_fix_exact_format` | Full string match: `"{old} is dead\n\nthink this is the one you want: {new}"` |
| `test_single_fix_without_verdict` | Same content even when verdicts=None |
| `test_empty_fixes` | Empty input → `"ran a check but found nothing worth fixing"` |
| `test_multiple_fixes_header` | Multi-fix body starts with `"found {N} dead links in the docs"` |

#### Behavioral suppression (4)
| Test | What it verifies |
|---|---|
| `test_single_fix_no_status_code` | HTTP status (e.g. `404`) is NOT in body |
| `test_single_fix_no_line_number` | Line number NOT in single-fix body |
| `test_multiple_fixes_arrows_are_ascii` | `->` present, `→` absent |
| `test_multiple_fixes_without_verdicts_omit_line_number` | `"line"` substring absent when no verdicts |

#### Multi-fix shape (2)
| Test | What it verifies |
|---|---|
| `test_multiple_fixes_with_line_numbers` | `"{file} line {LN}: {old} -> {new}"` format |
| `test_body_is_lowercase_apart_from_urls` | All non-URL alpha characters are lowercase |

#### Forbidden-substring sweep (21 parametrized tests)

`FORBIDDEN_AI_TELLS = ("docs:", "I ran", "**", "—", "→", "Verified", "automated")`

Three regimes × 7 tells = 21 parametrized assertions:
- `test_single_fix_no_ai_tells[<tell>]` for each tell
- `test_multiple_fixes_no_ai_tells[<tell>]` for each tell
- `test_empty_no_ai_tells[<tell>]` for each tell

These guarantee no AI-tell substring leaks back via a future refactor.

#### Markdown suppression (3)
| Test | What it verifies |
|---|---|
| `test_no_bold_markdown` | No `**` in single-fix body |
| `test_no_backticks` | No backticks in multi-fix body (file paths unwrapped) |
| `test_no_bot_words` | `bot`, `automated scanning`, `opt out` all absent |

## Coverage

```
src\gh_link_auditor\pipeline\pr_message.py      32 stmts   0 miss   100%
```

Every line of the module is exercised. The acceptance bar (≥95%) is met with margin.

## Regression Check

Full project suite run after the rewrite:

```
1863 passed, 1 skipped, 1 warning in 107.12s
```

No regressions. The +21 net delta vs. the 1842-test baseline reflects the test rewrite (17 old tests dropped, 45 new tests added, mostly from parametrization).

## Pre-existing flake worth flagging

Worktree's fresh Poetry venv did NOT have `playwright` installed before `poetry install` was rerun. Symptom: two `test_network.py::TestHeadlessBrowserGet` tests failed with `ModuleNotFoundError: No module named 'playwright'`. Resolved by `poetry install --no-root` inside the worktree. Not caused by this change. Worth noting in case the next worktree hits the same.
