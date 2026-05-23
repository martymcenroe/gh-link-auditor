# Implementation Report: #264 follow_redirects=True regression after #257

## Summary

#257 routed `github_resolver` from `urllib.request.urlopen` through `GitHubRateLimitedClient.get(url)`. urllib follows 301 redirects by default; `httpx.Client` does not. The whole point of `resolve_repo_redirect` is to follow GitHub's 301 for a renamed repo, so this silently broke rename detection in production.

Smoking gun in live Stage 3 output post-#257 merge (2026-05-23 09:51):

```
INFO  | github_resolver | GitHub redirect detected: Open-Catalyst-Project/ocp ->
INFO  | github_resolver | GitHub redirect detected: Open-Catalyst-Project/ocp ->
```

Empty after the arrow → `data.get("full_name", "")` returned `""` → 301 body (`{"message": "Moved Permanently", ...}`) had no `full_name`. Same 100% no-cand symptom that motivated #257, different cause.

## Changes

### `src/gh_link_auditor/github_resolver.py`

One line:

```python
r = active.get(url, follow_redirects=True)
```

with an inline comment naming the regression and pointing at #264. Matches the convention every other caller of `GitHubRateLimitedClient` already follows (`bulk_scan/inventory.py:204`, `:300`; `bulk_scan/language.py:36`).

### `tests/unit/test_github_resolver.py`

- `_FakeRateLimitedClient` gained a `call_kwargs: list[dict]` field; `.get()` records the kwargs of each call. Backwards-compatible (just an additional attribute).
- New test `TestGitHubApiGet.test_api_get_passes_follow_redirects_true` — asserts `fake.call_kwargs == [{"follow_redirects": True}]` after a single `_github_api_get` call. This is the precise contract: every API call must carry the kwarg. A future maintainer who deletes the flag will see this test fail with the literal diff.

## Why the existing #257 tests didn't catch this

- `TestResolveRepoRedirect` mocks `_github_api_get` directly with pre-followed response dicts. It never exercises the 301 path.
- `TestGitHubApiGet` (the rewritten class) mocks the client and feeds pre-shaped responses. The mock client doesn't behave like httpx — it just returns what you tell it.
- `TestRateLimitBehavior` stubs `_client.request` directly, synthesizing responses. The redirect machinery (which lives in `httpx.Client.send` for follow_redirects-aware paths) is never touched.

All three test layers mock *above* the layer that needed to be verified. The kwarg-passing test now sits at the exact boundary that was broken: the call from `_github_api_get` into the rate-limited client.

## Files modified

| File | Change |
|------|--------|
| `src/gh_link_auditor/github_resolver.py` | +1 kwarg + comment |
| `tests/unit/test_github_resolver.py` | +1 attr on fake; +1 new test |

## Test count

31 in `test_github_resolver.py` (+1 from #263's 30). Full suite: **2,158 passed, 1 skipped** (+1 net).

## Coverage

`src/gh_link_auditor/github_resolver.py` unchanged at 97% (the new line is exercised by the new test plus every test that goes through `_github_api_get`).

## Out of scope

- Diagnosing the `archive_client` log spam — tracked as #265, separate issue.
- Stripping the `token=` kwarg from `_github_api_get` — orthogonal cleanup; would churn callers for no behavior change.
