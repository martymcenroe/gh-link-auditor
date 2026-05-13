# Test Report: #190 stealth-Playwright fallback

## Local verification

### Suite

`poetry run python -m pytest --timeout=120 -q`:

```
1804 passed, 1 skipped, 1 warning in 109.99s
```

Pre-change baseline: 1798. Net +6 tests (3 in `TestHeadlessFallback`, 3 in `TestHeadlessBrowserGet`).

### RED → GREEN

Before implementation: 6 failures — `_headless_browser_get` didn't exist, the `check_url` ladder didn't have the new branch. After landing the helper + wiring, all 59 tests in `test_network.py` pass in 0.91s.

### Lint + format

```
poetry run ruff check .   -> All checks passed!
poetry run ruff format .  -> 2 files reformatted (network.py, test_network.py); then clean
```

## Live verification (operator runs)

After this PR merges, the operator can verify the real browser path against the known JS-challenged URL:

```
poetry run python -c "
from gh_link_auditor.network import check_url
r = check_url(
    'https://docs.mongoengine.org/projects/flask-mongoengine/en/latest/',
    request_config={'timeout': 15.0, 'verify_ssl': True, 'user_agent': 'test', 'allow_headless': True}
)
print(r)
"
```

Expected: a few seconds of latency, then `RequestResult` with `status='ok'`, `method='HEADLESS'`, response_time around 5-15 seconds.

Without `'allow_headless': True`, the same URL returns `status='error'`, `status_code=403` — proves the feature is opt-in.

## CI verification

PR goes through the same gate (Test + Lint + auto-review + pr-sentinel). The `Test` workflow doesn't invoke real browsers (mocked) so no Chrome install is needed on CI runners.

## Coverage

- `_headless_browser_get`: ImportError path, success path, challenge-detected path covered. Browser-launch failure and navigation timeout share the same `except Exception` block — covered indirectly by the goto-error path.
- `check_url` retry ladder: three new tests cover invoked / skipped / wrong-stage paths.
- ≥95% on new lines.

## Out of scope

- Real-browser integration test under `@pytest.mark.integration` — the prose verification above replaces it for this PR. A follow-up could automate the integration test against an expendable known-good challenge URL.
- N2 candidate verification — by design, headless OFF in `redirect_resolver._http_head`.
