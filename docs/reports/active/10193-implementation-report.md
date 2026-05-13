# Implementation Report: #193 HEAD-404 triggers GET fallback

## Summary

Some sites return HTTP 404 to HEAD requests but 200 to GET as an anti-crawler defense — confirmed today against `https://marketplace.visualstudio.com/items?itemName=ms-python.python`. Previously `should_retry(404, None)` returned `(False, False)`, so the pipeline declared these URLs dead without ever trying GET. This PR moves 404 into the same GET-fallback group as 403 and 405. 410 stays terminal (intentional permanent removal).

See LLD-193.

## Changes

### `src/gh_link_auditor/network.py`
- `should_retry` updated: 404 returns `(False, True)` (no retry, try GET). 410 kept at `(False, False)`. 403 and 405 unchanged.
- The existing `get_fallback_attempted` flag in `check_url` already prevents GET→GET looping; no change needed there.

### `tests/unit/test_network.py`
- New `TestHeadToGetFallback404` class (2 tests): HEAD 404 + GET 200 → ok/GET; HEAD 404 + GET 404 → error/404 (genuinely dead).
- Existing `TestShouldRetry::test_404_no_retry` (asserted old behavior) renamed to `test_404_get_fallback` and updated to `(False, True)`.

### `tests/unit/test_check_links_fallback.py`
- `test_404_does_not_trigger_fallback` (old behavior) replaced with `test_404_triggers_fallback`. Added `test_410_does_not_trigger_fallback` so the 410 boundary is explicit.

## Files modified

| File | Change |
|------|--------|
| `src/gh_link_auditor/network.py` | `should_retry`: 404 now in GET-fallback group |
| `tests/unit/test_network.py` | new `TestHeadToGetFallback404`; updated `test_404_no_retry` |
| `tests/unit/test_check_links_fallback.py` | flipped 404 assertion, added 410 boundary test |
| `docs/lld/active/LLD-193.md` | NEW design |

## Test count

`pytest --co -q` collects **1807 tests** (was 1804, +3 net from this PR).

## Operator impact

Audits against sites that 404-block HEAD (Microsoft Marketplace, likely Apple/Atlassian similar) will no longer surface their URLs as dead in N4. Today's python-guide finding #1 (`marketplace.visualstudio.com/items?itemName=ms-python.python`) drops from the dead-link list after this merges.
