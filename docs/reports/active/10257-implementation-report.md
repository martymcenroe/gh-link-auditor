# Implementation Report: #257 route github_resolver through GitHubRateLimitedClient

## Summary

`github_resolver` was calling GitHub's REST API through raw `urllib.request.urlopen` — no throttle, no quota awareness, no backoff on 403/429. Under Stage 3 with ≥16 concurrent workers it hit primary `X-RateLimit-Remaining=0` or the secondary rate limit and silently returned `None`, swallowing every `github_api_redirect` candidate a renamed-repo URL would have surfaced. The current Stage 3 restart was showing `recent_no_cand_rate: 99.8%` within 9 minutes — the documented fingerprint of this exact failure mode.

This PR routes all `github_resolver` API calls through the existing `gh_link_auditor.bulk_scan.gh_client.GitHubRateLimitedClient` (#224), which provides per-request throttle, low-watermark quota wait, `Retry-After` + `X-RateLimit-Reset` honoring, exponential backoff with jitter, and telemetry counters.

See LLD-257.

## Changes

### `src/gh_link_auditor/github_resolver.py`

- New module-level `_default_client: GitHubRateLimitedClient | None` with `_default_client_lock`. Process-wide singleton so the 32 worker resolvers share quota counters — per-instance clients would split the quota and collectively exceed 5K/hr.
- New `_get_default_client()` — double-checked locking. Imports `auth.resolve_github_token` and `bulk_scan.gh_client.GitHubRateLimitedClient` *inside* the function to avoid module-load circularity (`bulk_scan.runner` → `link_detective` → `github_resolver`).
- `_github_api_get(url, token=None, client=None)` body rewritten:
  - calls `active.get(url)` on the injected or default client
  - returns `None` on `httpx.HTTPError`, 404, ≥400 status, or non-JSON body
  - `token=` kwarg retained for backwards compatibility but unused (the client carries its own token)
- `GitHubResolver.__init__(token=None, *, client=None)` — new keyword-only `client=` for injection. Stored on `self._client` and threaded into `resolve_repo_redirect`'s call to `_github_api_get`.
- `urllib.request`, `urllib.error`, `json` imports removed. `httpx` added (it's already a top-level project dep).

### `tests/unit/test_github_resolver.py`

- New inline `_FakeHttpxResponse` and `_FakeRateLimitedClient` test doubles — no MagicMock, consistent with the `tests/fakes/` pattern.
- `TestGitHubApiGet` rewritten (5 tests): success / 404 / non-404 status / `httpx.HTTPError` / non-JSON body. Mock target moved from `urllib.request.urlopen` to a fake client passed via `client=`. `test_api_get_with_token` dropped (the token is no longer wired through urllib; behavior is owned by the client).
- New `TestClientInjection` (2 tests): resolver uses injected client, resolver falls back to `_get_default_client` when no client passed.
- New `TestDefaultClientFactory` (2 tests): factory is a singleton (double construction yields same instance, only one underlying construction); empty token from `resolve_github_token` is passed as `None`.
- New `TestRateLimitBehavior` (3 tests, end-to-end through the real `GitHubRateLimitedClient`):
  - 403 + `X-RateLimit-Remaining: 0` → backoff sleep → retry succeeds, `total_secondary_limits == 1`
  - low-watermark + `_reset_at` 3s out → sleep ≥3s (gh_client adds a 1s safety buffer past reset, so the real wait is ~4s)
  - 429 + `Retry-After: 1` → sleep exactly 1.0s, `total_429s == 1`

## Files modified

| File | Change |
|------|--------|
| `src/gh_link_auditor/github_resolver.py` | rewrite — urllib → GitHubRateLimitedClient + lazy default + injection |
| `tests/unit/test_github_resolver.py` | rewrite TestGitHubApiGet; +3 new classes (TestClientInjection, TestDefaultClientFactory, TestRateLimitBehavior); +7 net tests |
| `docs/lld/active/LLD-257.md` | NEW — design |

## Test count

`pytest --co -q` collects **2,157 passed, 1 skipped** after this change (vs. ~2,150 prior). Net +7 from the new resolver classes; the existing 23 in `test_github_resolver.py` continue to pass unchanged.

## Coverage

`src/gh_link_auditor/github_resolver.py`: **97%** (87/90 statements). The 3 uncovered lines are pre-existing defensive paths (URL-parse exception fallthrough in `is_github_url`; the empty-path branch of raw.githubusercontent reconstruction). Above the project ≥95% hard rule for changed code.

## Out of scope

- Wiring the bulk-scan runner's `GitHubRateLimitedClient` instance into `link_detective.GitHubResolver` for fully unified quota accounting across stages. The `client=` injection point is exposed; wiring is a follow-up if telemetry shows the two stacks fighting for the same 5K/hr window.
- `archive_client` (Wayback CDX) and `redirect_resolver` (generic HEAD probes) rate-limit overhauls — different upstreams, separate issues.
- Migrating `from src.logging_config import setup_logging` to a packaged import — LLD-256 Part C scope.
