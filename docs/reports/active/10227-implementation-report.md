# 10227 Implementation Report

**Issue:** #227
**Branch:** `227-malformed-url-skip`

## Changes

| File | Change |
|---|---|
| `src/gh_link_auditor/false_positives.py` | New `_safe_hostname(url)` helper. Five predicates use it: `is_placeholder_url`, `is_always_alive_domain`, `is_bot_blocked`, `is_api_test_endpoint`. `is_placeholder_path` gets its own narrow try/except around `urlparse(url).path`. |
| `src/gh_link_auditor/bulk_scan/inventory.py` | `filter_url` gets a leading `try: urlparse(url) except ValueError: return False` guard so a malformed URL skips this one entry instead of crashing the whole repo's inventory. |
| `tests/unit/test_false_positives.py` | New `TestMalformedUrlSafety` class — 10 tests covering bracketed-bare and NFKC-bad-netloc inputs against all five hardened predicates. |
| `tests/unit/bulk_scan/test_inventory.py` | Two new `filter_url` regression tests for the same two real-world malformed-URL shapes. |
| `docs/lld/active/LLD-227.md` | New LLD. |

## Behavior change

Before: an extracted URL of `https://[unclosed` (from Markdown like `[link](https://[unclosed`) inside a doc would raise `ValueError("Invalid IPv6 URL")` from `urlparse`, propagate up through `filter_url` and `inventory_repo`, and get caught by the broad `except Exception` in `runner.run_inventory`. The WHOLE repo would be marked status=error and lose all its findings.

After: malformed URLs return False from `filter_url` and are silently dropped. The rest of the repo's URLs continue through to extraction and storage normally.

## Production-data alignment

In bulk-scan run `bulk-20260514T042627Z` (a healthy 7-hour 91%-complete run, stopped intentionally), 60 of 6,900 processed repos errored on this exact bug:

- 50 × `Invalid IPv6 URL`
- 9 × `NFKC normalization`
- 1 × `non-printable ASCII character`

All three classes are covered by the regression tests.

## Verification

- `poetry run pytest tests/unit/test_false_positives.py tests/unit/bulk_scan/test_inventory.py` → 132 passing
- Full suite: `poetry run pytest -q` → 2055 passed, 1 skipped (was 2043 before)
- `ruff check .` → All checks passed
- `ruff format .` → 215 files left unchanged
- Coverage on `false_positives.py`: 100%
