# Test Report: #198 CDN-None stealth fallback

## Local verification

`poetry run python -m pytest --timeout=120 -q` → **1828 passed, 1 skipped**.

Pre-change baseline: 1820. Net +8 tests.

## RED → GREEN

Tests added first failed with `AttributeError: module 'gh_link_auditor.network' does not have the attribute '_resolves_to_cdn'`. After adding the helper + the new conditional in `check_url`, all 8 tests pass in 0.09s.

## Lint + format

`ruff check . && ruff format --check .` clean, no reformat needed.

## Coverage

- `_resolves_to_cdn` happy paths (Cloudflare + Fastly), miss path (non-CDN), failure paths (DNS error, no hostname). 5 tests.
- `check_url` new branch: fires when conditions met, skipped when CDN check fails, skipped when opt-in flag off. 3 tests.

Existing tests unaffected.

≥95% on changed lines.

## Out of scope

Real-world verification against `pythonjobshq.com` happens at the next Phase 4 run.
