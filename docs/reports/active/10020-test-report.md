# Test Report: #20 Cheery Littlebottom — Dead Link Detective

**Date:** 2026-03-18

## Summary
- Total tests: 1070 passed, 1 skipped
- New tests: 4 (coverage gap closure)

## Coverage (target files)
| File | Before | After |
|------|--------|-------|
| `redirect_resolver.py` | 97% | 99% |
| `url_heuristic.py` | 96% | 100% |
| `n2_investigate.py` | 91% | 100% |
| `similarity.py` | 100% | 100% |
| `link_detective.py` | 100% | 100% |
| `github_resolver.py` | 100% | 100% |
| `archive_client.py` | 100% | 100% |

## Remaining Uncovered
- `redirect_resolver.py:68` — Inner `NoRedirectHandler.redirect_request` callback, only exercised by real HTTP redirect (unreachable in unit test without live server)

## New Test Breakdown

### test_redirect_resolver.py (+1)
- `test_invalid_ip_from_getaddrinfo_skipped`: getaddrinfo returns invalid IP string, verifies ValueError is caught and skipped (line 236-237)

### test_url_heuristic.py (+2)
- `test_empty_slug_returns_empty_list`: Title "!!!" produces empty slug, returns no candidates (line 61)
- `test_version_variants_included_in_candidates`: Path with `/v1/` includes v2/latest variants (line 83)

### test_n2.py (+1)
- `test_lazy_import_calls_link_detective`: Exercises _run_investigation lazy import of LinkDetective (lines 31-34)

## Lint/Format
- `ruff check`: clean
- `ruff format`: clean
