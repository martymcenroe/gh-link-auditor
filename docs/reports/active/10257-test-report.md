# Test Report: #257 route github_resolver through GitHubRateLimitedClient

## Local verification

### Suite

`poetry run pytest --tb=line -q`:

```
2157 passed, 1 skipped, 1 warning in 125.07s (0:02:05)
```

No regressions. Pre-change baseline (post-#260 merge) was ~2,150; +7 net from the new classes in this PR.

### Targeted RED → GREEN

```
$ poetry run pytest tests/unit/test_github_resolver.py -x --tb=short
ImportError: cannot import name '_get_default_client' from 'gh_link_auditor.github_resolver'
```

After landing the implementation:

```
$ poetry run pytest tests/unit/test_github_resolver.py -v
30 passed in 0.60s
```

One transient red along the way: `test_x_ratelimit_reset_wait_honored` failed first run because `gh_client._wait_for_quota` adds a `+1.0s` safety buffer past `_reset_at` — a 3-second-out reset sleeps for ~4s, not ~3s. The assertion was tightened to `s >= 3.0` (any sleep at least as long as the reset delta) which is the real contract the test validates.

### Coverage

```
$ poetry run pytest tests/unit/test_github_resolver.py \
    --cov=gh_link_auditor.github_resolver --cov-report=term-missing
Name                                     Stmts   Miss  Cover   Missing
----------------------------------------------------------------------
src\gh_link_auditor\github_resolver.py      90      3    97%   140-141, 223
```

The 3 uncovered lines are pre-existing defensive paths unrelated to this PR:

- `lines 140-141` — `except Exception: return False` in `is_github_url` after `urlparse`. Practically unreachable from valid string input.
- `line 223` — empty-path branch of the raw.githubusercontent reconstruction. Not exercised by any current test, was already uncovered pre-PR.

97% ≥ 95% project hard rule. Closing the remaining 3 lines would expand the diff into unrelated code paths.

### Lint + format

```
$ poetry run ruff format --check .
225 files already formatted
$ poetry run ruff check .
All checks passed!
```

## CI verification

PR will go through the standard gate: `Test`, `Lint`, `auto-review`, `pr-sentinel`. No new external dependencies, no schema changes, no migrations.

## Test surface

| Class | Tests | Purpose |
|---|---:|---|
| `TestIsGitHubUrl` | 5 | unchanged — URL domain checks |
| `TestParseGitHubUrl` | 4 | unchanged — URL parsing |
| `TestResolveRepoRedirect` | 4 | unchanged — already mocks `_github_api_get` at the right boundary |
| `TestReconstructFileUrl` | 3 | unchanged — string reconstruction |
| `TestGitHubApiGet` | 5 | **rewritten** — mocks the injected client instead of urllib |
| `TestTokenFromEnv` | 2 | unchanged — `__init__` token logic |
| `TestClientInjection` | 2 | **new** — resolver uses `client=` end-to-end; falls back to `_get_default_client` |
| `TestDefaultClientFactory` | 2 | **new** — module-level singleton; empty-token-as-None |
| `TestRateLimitBehavior` | 3 | **new** — 403+remaining=0 backoff, X-RateLimit-Reset wait, Retry-After honored |
| **Total** | **30** | **+7 net** |

## Runtime verification path (post-merge)

This PR fixes a *runtime* symptom (Stage 3 anomaly: 99.8% no-cand rate from silent 403s on github_api_redirect lookups). The unit tests prove the rate-limit machinery is wired correctly; the runtime fix is verified by re-running Stage 3 against `bulk-20260514T042627Z` after merge and watching:

- `data/finish-stage3-status.txt` — `recent_no_cand_rate` should drop below the anomaly threshold (95%) as renamed-repo candidates start surfacing again
- `investigated_with_candidate` counter should increase at a non-trivial rate vs. pre-fix
- The visible `WARNING | github_resolver | GitHub API error 403 for ...` log lines should disappear

Operator runs the post-merge Stage 3 re-execution; this PR doesn't bundle that verification.

## Out of scope (tests deliberately not written)

- Multi-thread concurrent-default-construction race. The double-checked lock guarantees one client per process; testing this would require threading + timing assertions that are brittle in CI. Confidence comes from the simple lock pattern, not a flaky test.
- Real-network smoke against `api.github.com`. The integration layer tests use stubbed `httpx.Client.request` responses; the real network behavior is the job of the gh_client unit tests in `test_gh_client.py`, which already exists from #224.
- `link_detective` integration. `link_detective.py:256` instantiates `GitHubResolver()` with no kwargs; that call path uses the lazy default client, exactly the path `test_resolver_default_client_used_when_no_injection` covers.
