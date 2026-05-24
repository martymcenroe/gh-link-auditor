# 10243 - Test Report

**Issues:** #243, #213
**Branch:** `243-nice-to-haves`

## Test count

| Stage | Count |
|---|---|
| Before this PR | 2407 passed, 1 skipped |
| After this PR | 2424 passed, 1 skipped |
| Net | +17 new tests |

## New tests

### `tests/unit/test_false_positives.py` (14 tests)

- `TestIsFalsePositive` (5 new): patreon, github sponsors path, ko-fi, buymeacoffee → False positive; github regular repo path → not flagged
- `TestIsDonationUrl` (9 tests): patreon (with + without www); opencollective; github sponsors path; github non-sponsors path (not flagged); paypal /donate; paypal regular URL (not flagged); subdomain match; unknown domain not flagged

### `tests/unit/pipeline/test_n4.py` (3 tests)

- `test_dead_domain_skips_site_queries` — `dead_domain=True` emits no `site:` query; still has topic + URL searches
- `test_dead_domain_false_keeps_site_queries` — default behavior preserved
- `test_dead_domain_with_no_name_still_emits_url_triangulation` — bare-domain + dead_domain=True still produces the URL-quote triangulation search

## No regressions

`poetry run pytest -q`: **2424 passed, 1 skipped**.

## Lint

| Check | Result |
|---|---|
| `poetry run ruff format --check .` | 246 files already formatted |
| `poetry run ruff check .` | All checks passed |
