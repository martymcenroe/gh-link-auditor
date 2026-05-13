# Implementation Report: #190 stealth-Playwright fallback for JS-challenged URLs

## Summary

Cloudflare-style JavaScript challenges return HTTP 403 to bot clients while loading fine in real browsers (today's case: `https://docs.mongoengine.org/projects/flask-mongoengine/en/latest/`). `network.check_url`'s 403 retry ladder previously maxed out at "modern Chrome UA on GET" — any URL still 403 after that was reported dead. This PR adds a final tier: load the URL in real headless Chrome via Playwright with stealth patches, wait for the JS challenge to resolve, return `ok` if we landed on a non-challenge page.

The fallback is **opt-in** via `request_config["allow_headless"]` (default `False`). N1's scan enables it; N2's frequent per-candidate `_http_head` probes do not (cost-bound).

See LLD-190.

## Changes

### `pyproject.toml`
- New deps: `playwright (>=1.59.0)`, `playwright-stealth (>=2.0.3)`.
- **No Chromium download.** The helper uses `channel="chrome"` which reuses the user's installed Chrome. Matches the career project pattern at `C:\Users\mcwiz\Projects\career\dashboard\cli\browser.ts`.

### `src/gh_link_auditor/network.py`
- New `_headless_browser_get(url, timeout_s)` function. Launches Chrome via `playwright.sync_api.sync_playwright()`, applies `playwright_stealth.Stealth().apply_stealth_sync(page)`, navigates with `wait_until="networkidle"`, checks final `page.title()` against the `_CHALLENGE_TITLE_MARKERS` tuple (`"checking your browser"`, `"just a moment"`).
- Returns `RequestResult` with `method="HEADLESS"`. Handles five outcomes: success, still-on-challenge, navigation timeout, browser launch failure, ImportError on playwright.
- New conditional in `check_url`'s retry ladder (after the existing browser-UA retry): if `status_code == 403 and browser_ua_attempted and request_config.get("allow_headless")`, return `_headless_browser_get(url, timeout_s=request_config["timeout"] * 2)`.
- Bugfix in the same area: the browser-UA retry was reconstructing `RequestConfig` via `RequestConfig(...)` constructor, which silently drops any extra keys (including `allow_headless`). Switched to `{**request_config, "user_agent": _BROWSER_RETRY_UA}` to preserve all keys.

### `src/gh_link_auditor/pipeline/nodes/n1_scan.py`
- `_check_single_url` now builds a `RequestConfig` with `allow_headless=True` and passes it to `check_url`. One probe per URL, so the ~5-15s headless cost on JS-challenged URLs is acceptable here. The N1→check_url path is the only callsite that enables it.

## Tests

### `tests/unit/test_network.py`

**`TestHeadlessFallback` (3 tests)** — exercises the new retry-ladder branch with `_headless_browser_get` mocked:
- `test_headless_fallback_invoked_when_allow_headless_true` — 403 cascade with the flag set ⇒ `_headless_browser_get` called, result is `ok`.
- `test_headless_fallback_skipped_when_flag_absent` — same cascade with default config ⇒ NOT called, result is 403.
- `test_headless_fallback_only_after_browser_ua_retry` — browser-UA retry succeeds on iter 3 ⇒ headless NEVER invoked (proves it's a true last-resort).

**`TestHeadlessBrowserGet` (3 tests)** — exercises `_headless_browser_get` directly with lightweight fakes for Playwright objects:
- `test_returns_error_when_playwright_unavailable` — ImportError path returns `error="playwright unavailable"`.
- `test_returns_ok_when_navigation_succeeds` — fake browser path returns `ok` + status code.
- `test_detects_still_on_challenge_page` — fake page with "Checking your browser" title ⇒ `error="still on JS challenge page after networkidle"`.

The fakes are typed plain classes (`_Resp`, `_Page`, `_Ctx`, `_Browser`, `_Chromium`, `_Playwright`, `_SyncCM`, `_FakeStealth`) — no `MagicMock` per project policy.

### Real-browser integration test

Not included in this PR. The deferred verification command lives in the test report's "Live verification" section and is run by the operator with Chrome on the path. CI's unit gate stays stable.

## Files modified

| File | Change |
|------|--------|
| `pyproject.toml` + `poetry.lock` | playwright + playwright-stealth |
| `src/gh_link_auditor/network.py` | `_headless_browser_get` helper; wire into `check_url`; bugfix preserving optional config keys |
| `src/gh_link_auditor/pipeline/nodes/n1_scan.py` | enable `allow_headless=True` for the audit-pipeline probe |
| `tests/unit/test_network.py` | 6 new tests across `TestHeadlessFallback` and `TestHeadlessBrowserGet` |
| `docs/lld/active/LLD-190.md` | NEW design |

## Test count baseline

`pytest --co -q` collects **1804 tests** post-change (was 1798, +6 net).

## Out of scope

- N2 per-candidate headless verification — cost-prohibitive; trust state machine already handles tier-2 candidate gating.
- Persistent state / cookie jar reuse across runs.
- Headed mode (browser window visible).
- Async API — sync was sufficient for blocking single-URL probes.
