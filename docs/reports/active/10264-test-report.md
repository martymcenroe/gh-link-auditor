# Test Report: #264 follow_redirects=True regression after #257

## Local verification

### Targeted RED → GREEN

Before the fix (after only the test was added):

```
$ pytest tests/unit/test_github_resolver.py::TestGitHubApiGet::test_api_get_passes_follow_redirects_true --tb=short
F
AssertionError: assert [{}] == [{'follow_redirects': True}]
  At index 0 diff: {} != {'follow_redirects': True}
1 failed in 0.16s
```

After the one-line fix:

```
$ pytest tests/unit/test_github_resolver.py
31 passed in 0.58s
```

### Full suite

```
$ pytest -q --tb=line
2158 passed, 1 skipped, 1 warning in 125.37s (0:02:05)
```

No regressions vs. the post-#263 baseline (2,157 passed, 1 skipped).

### Lint + format

```
$ ruff format src/gh_link_auditor/github_resolver.py tests/unit/test_github_resolver.py
2 files left unchanged
$ ruff check src/gh_link_auditor/github_resolver.py tests/unit/test_github_resolver.py
All checks passed!
```

## CI verification

Standard gate: Test, Lint, auto-review, pr-sentinel.

## Runtime verification path

This PR fixes a *runtime* symptom — the 100% no-candidate rate that persisted after #257. The unit test proves the kwarg is in the call; the runtime fix is verified by re-running Stage 3 against `bulk-20260514T042627Z` after merge and watching:

- `data/finish-stage3-status.txt` — `investigated_with_candidate` should start incrementing (it sat at 0 during the post-#257 run that showed the empty-arrow log lines).
- `recent_no_cand_rate` should drop below 95% within the first few hundred investigations as renamed-repo redirects start surfacing valid candidates again.
- `github_resolver` INFO log lines should now show the full target after the arrow: `GitHub redirect detected: Open-Catalyst-Project/ocp -> facebookresearch/fairchem` (or similar) — not empty.

The operator runs the post-merge Stage 3 re-execution; this PR doesn't bundle that verification.

## Lessons learned (for the LL log)

- **urllib auto-follows 301; httpx does not.** When migrating any urllib-based call to an `httpx.Client`-based one, explicit `follow_redirects=True` is almost always required when the endpoint can legitimately redirect. Easy to miss because all the existing #257 tests mocked above the boundary that mattered.
- **Mock-above-the-defect tests cannot catch defects at that boundary.** The #257 suite was thorough at every layer except the one that broke. A test that asserts the literal kwarg passed to the underlying client closes the gap, and is cheap.

## Out of scope (tests deliberately not written)

- Real-network integration against `api.github.com` to verify httpx actually follows 301 when `follow_redirects=True`. That's httpx-library behavior, not ours; we'd be re-testing httpx.
- Coverage of the rate-limited client's redirect-aware path (e.g., what happens if both the redirect target and the original URL are rate-limited). #224's existing tests at `tests/unit/bulk_scan/test_gh_client.py` cover the rate-limit machinery; this PR is scoped to the kwarg passthrough.
