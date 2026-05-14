# Test Report — #211 (SE allow-list)

## Inventory

### `TestIsAlwaysAliveDomain` — 21 new tests

Domain coverage:

| Test | URL |
|---|---|
| `test_stackoverflow_root` | `https://stackoverflow.com/` |
| `test_stackoverflow_short_answer` | `/a/N` permalink |
| `test_stackoverflow_short_question` | `/q/N` permalink |
| `test_stackoverflow_long_question` | `/questions/N/slug` |
| `test_stackexchange_subdomain_physics` | `physics.stackexchange.com` |
| `test_stackexchange_subdomain_unix` | `unix.stackexchange.com` |
| `test_stackexchange_subdomain_security` | `security.stackexchange.com` |
| `test_stackexchange_bare` | `stackexchange.com` (no subdomain) |
| `test_serverfault` | `serverfault.com` |
| `test_superuser` | `superuser.com` |
| `test_askubuntu` | `askubuntu.com` |
| `test_mathoverflow` | `mathoverflow.net` |
| `test_stackapps` | `stackapps.com` |

Edge cases:

| Test | Asserts |
|---|---|
| `test_http_scheme_too` | Accepts http:// not just https:// |
| `test_unrelated_domain_not_skipped` | example.com → False |
| `test_github_not_skipped` | github.com → False |
| `test_wikipedia_not_skipped` | wikipedia.org → False (different policy class) |
| `test_stackoverflow_typosquat_not_skipped` | `stackoverflow-clone.com` → False (anti-typosquat) |
| `test_empty_url` | `""` → False |
| `test_no_host` | `"not-a-url"` → False |
| `test_case_insensitive_host` | `StackOverflow.com` → True |

### `TestIsFalsePositive` additions — 3 new tests

| Test | Asserts |
|---|---|
| `test_stackoverflow_categorical_skip` | `is_false_positive("...stackoverflow.com/a/N")` → True (no status) |
| `test_stackexchange_subdomain_categorical_skip` | Subdomain → True (no status) |
| `test_askubuntu_categorical_skip` | askubuntu.com → True (no status) |

### Modified test

`test_bot_blocked_without_status` — assertion inverted (now expects True). Added `test_non_se_bot_blocked_without_status_not_filtered` to confirm non-SE bot-blocked domains still need a status code.

## Coverage

`is_always_alive_domain` is 13 lines (function body + branch). All branches exercised:
- empty hostname → return False (`test_empty_url`, `test_no_host`)
- exact-domain match → return True (`test_stackexchange_bare`)
- subdomain match → return True (`test_stackexchange_subdomain_*`)
- no match → return False (`test_unrelated_domain_not_skipped`, `test_stackoverflow_typosquat_not_skipped`)

## Regression check

```
1950 passed, 1 skipped, 1 warning in 114.27s
```

The 1 modified test was `test_bot_blocked_without_status` (inversion intentional, documented in the test comment).

## Effect on N1

Before #211, N1's `run_link_scan` would emit a `DeadLink` for any SE URL that returned non-2xx (bot-blocked OR transient OR misclassified 302). After #211, the URL is filtered in the pre-check at line 277 — the function `_check_single_url` is never called for SE hosts.

Estimated production impact for the python-guide bulk scan: ~150-300 fewer false-positive verdicts per repo (based on operator-observed rate during 2026-05-13 live run).
