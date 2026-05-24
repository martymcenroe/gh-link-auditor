# 10282 - Test Report

**Issues:** #282, #315, #316
**Branch:** `282-lld-and-prereq-extensions`

## Test count

| Stage | Count |
|---|---|
| Before this PR | 2237 passed, 1 skipped |
| After this PR | 2247 passed, 1 skipped |
| Net | +10 new tests |

## New tests

### `tests/unit/test_network.py::TestCheckUrlFinalUrl` (5 tests, #315)

1. `test_final_url_matches_requested_when_no_redirect` — direct 2xx returns `final_url == requested URL`
2. `test_final_url_reflects_redirect_target` — when `response.url` differs from requested URL, `final_url` carries the destination
3. `test_final_url_falls_back_to_requested_when_response_lacks_url` — fake response with `url=None` falls back to the requested URL
4. `test_final_url_none_on_dns_failure` — DNS failure → `final_url is None`
5. `test_final_url_populated_on_http_error` — HTTPError carries `exc.url`, so `final_url` populates even on 4xx

### `tests/unit/test_repo_quality.py::TestFetchRepoMetadataExtended` (5 tests, #316)

1. `test_archived_repo_surfaces_true` — `archived: true` in jq output → `quality.archived is True`
2. `test_disabled_repo_surfaces_true` — `disabled: true` + `license: null` → `quality.disabled is True`, `quality.license is None`
3. `test_license_spdx_is_captured` — `Apache-2.0` SPDX id captured
4. `test_missing_license_returns_none` — explicit `license: null` returns None
5. `test_default_archived_disabled_when_keys_missing` — older jq output omitting new keys defaults to `False` / `None` (backward compat)

## Modified existing tests

### `tests/unit/test_network.py`

1. `TestMakeRequestEdgeCases::test_socket_timeout_direct` — 4-tuple unpack → 5-tuple; assert `final_url is None`
2. `TestMakeRequestEdgeCases::test_broken_pipe` — same
3. `TestMakeRequestEdgeCases::test_unexpected_exception` — same
4. `TestCheckUrlFullFlow::test_check_url_default_configs` — `expected_keys` set now includes `"final_url"`

### `tests/unit/test_repo_quality.py`

1. `TestFetchRepoMetadata::test_fetches_stars_and_pushed_at` — jq mock JSON updated to include the new `archived`/`disabled`/`license` fields (forward-compatible with the new query); existing assertions on `stars` / `pushed_at` / `contributors` unchanged

## Modified test fakes

`tests/fakes/http.py`:

- `FakeURLResponse.__init__` now accepts an optional `url: str | None = None` kwarg
- Exposes `self.url` so tests can simulate redirect-resolved URLs without MagicMock

## No regressions

`poetry run pytest -q` reports **2247 passed, 1 skipped** (was 2237 passed, 1 skipped before this PR). The single skipped test pre-dates this work (live/integration marker). No tests were silenced, deleted, or `xfail`'d.

## Lint

| Check | Result |
|---|---|
| `poetry run ruff format --check .` | 234 files already formatted (1 file auto-fixed in `tests/unit/test_repo_quality.py` during this PR; verified clean after) |
| `poetry run ruff check .` | All checks passed |

## Coverage on new production code

| Symbol | Tests covering it |
|---|---|
| `network.RequestResult.final_url` field | All `TestCheckUrlFinalUrl` tests + the keyset assertion in `test_check_url_default_configs` |
| `network._make_request` 5-tuple return | `TestMakeRequestEdgeCases` (error paths) + every `TestCheckUrl*` test (success paths via `check_url`) |
| `network._headless_browser_get` `final_url` population | Existing `TestHeadlessBrowserGet` tests now exercise the defensive `getattr(page, "url", None)` path implicitly |
| `RepoQuality.{archived, disabled, license}` fields | `TestFetchRepoMetadataExtended` (5 tests) + `test_fetches_stars_and_pushed_at` (passthrough sanity) |
| `repo_quality.fetch_repo_metadata` extended jq + assignment | Same |

All new lines are exercised; project hard rule ≥95% met.

## Phase A regression check

`git grep -i -E '(A\+\+|PRs filed|contribution graph|green square|naked ambition)'` on tracked files in the worktree returns **0 hits**. Phase A scrub remains clean.
