# 10227 Test Report

**Issue:** #227
**Branch:** `227-malformed-url-skip`

## Test inventory

12 new tests:

### `tests/unit/test_false_positives.py::TestMalformedUrlSafety` (10)

Each of the five hardened predicates gets two regression tests — one with a bracketed-bare URL (`https://[unclosed`) that triggers `ValueError("Invalid IPv6 URL")` from `urlparse`, one with an NFKC-bad netloc (`https://visualstudio.microsoft.com)：用于编译`) that triggers `ValueError("netloc ... contains invalid characters under NFKC normalization")`.

- `test_is_placeholder_url_bracketed`
- `test_is_placeholder_url_nfkc`
- `test_is_always_alive_domain_bracketed`
- `test_is_always_alive_domain_nfkc`
- `test_is_bot_blocked_bracketed`
- `test_is_bot_blocked_nfkc`
- `test_is_api_test_endpoint_bracketed`
- `test_is_api_test_endpoint_nfkc`
- `test_is_placeholder_path_bracketed`
- `test_is_placeholder_path_nfkc`

All assert the predicate returns False (or doesn't match) WITHOUT propagating `ValueError`.

### `tests/unit/bulk_scan/test_inventory.py::TestFilterUrl` (2)

- `test_bracketed_bare_url_skipped` — `filter_url("https://[unclosed")` returns False instead of raising.
- `test_nfkc_bad_netloc_skipped` — `filter_url("https://visualstudio.microsoft.com)：用于编译")` returns False.

## Verification of bug reproduction

Pre-fix, on Python 3.14:

```python
>>> from urllib.parse import urlparse
>>> urlparse("https://[unclosed")
ValueError: Invalid IPv6 URL
>>> urlparse("https://visualstudio.microsoft.com)：用于编译")
ValueError: netloc 'visualstudio.microsoft.com)：用于编译' contains invalid characters under NFKC normalization
```

Post-fix:

```python
>>> from gh_link_auditor.false_positives import is_placeholder_url
>>> is_placeholder_url("https://[unclosed")
False
>>> is_placeholder_url("https://visualstudio.microsoft.com)：用于编译")
False
```

## Results

| Suite | Result |
|---|---|
| Targeted (132 tests) | All pass |
| Full repo | 2055 passed, 1 skipped, 1 warning (was 2043 pre-change) |
| Ruff check | All checks passed |
| Ruff format | No changes |
| Coverage on `false_positives.py` | 100% |

## Out of scope (separate follow-ups)

- Tightening `_URL_RE` in `inventory.py` to also stop at `[`. Risks regression on legitimate IPv6 URLs; only needed if a real-world IPv6 URL ever surfaces.
- Issue #226 — circuit-breaker hardening for the `GitHubRateLimitedClient` (rate-limit defense-in-depth). Surfaced during the same diagnosis but not on this PR's path.
