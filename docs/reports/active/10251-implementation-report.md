# 10251 — Implementation Report

**Issue:** #251 — fix(inventory): sanitize doc paths from GitHub trees API
**Branch:** `251-sanitize-doc-paths`
**LLD:** `docs/lld/active/LLD-251.md`

## Changes

### `src/gh_link_auditor/bulk_scan/inventory.py`

Two surgical additions:

1. New helper `_is_safe_doc_path(path: str) -> bool`. Returns `False` for any path containing a C0 control character (`ord(c) < 0x20`) and for the empty string. Real doc files never have these in their names; dropping them is the right behavior.

2. `_list_doc_files` now consults `_is_safe_doc_path` between the `type=='blob'` check and the doc-extension append. Pathological paths are dropped silently (logged at DEBUG with the offending path's `repr()` so it stays in logs without polluting normal output). The rest of the repo's docs proceed normally.

3. `_fetch_raw` now URL-encodes the path component via `urllib.parse.quote(path, safe='/')` when composing the raw-CDN URL. `safe='/'` keeps directory separators literal so the path structure survives encoding. This is a belt-and-suspenders defense — control chars are already filtered by (1), but spaces, `#`, `?`, accented chars, etc. still arrive and would historically have caused trouble with some clients.

### `tests/unit/bulk_scan/test_inventory_sanitize.py` (new file)

12 tests across three classes covering:

* **Path-filter layer**: `\n`, `\r`, `\t`, `\x00` paths dropped; normal paths kept; non-doc extensions still filtered; empty tree handled.
* **URL-encoding layer**: space → `%20`, `#` → `%23`, `?` → `%3F`; directory separators kept literal; normal ASCII paths unchanged.
* **End-to-end**: `inventory_repo` returns a clean list when given a tree response with mixed pathological and normal paths — the original failure mode (whole-repo abort) is gone.

Uses small typed fakes (`_FakeTreeResp`, `_FakeAPIClient`, `_RecordingRawClient`) local to the test file. No `MagicMock`.

## Behavior change summary

| Input | Before | After |
|---|---|---|
| Tree with one `\n`-containing path | `httpx.InvalidURL`; whole repo errored | `\n` path dropped; rest of repo inventoried normally |
| Path with literal space (`docs/My File.md`) | Worked depending on client; could 404 | URL-encoded to `docs/My%20File.md`; raw CDN returns the file |
| Path with `#` or `?` | URL parsing ambiguity (fragment / query) | Encoded; no ambiguity |
| Path with directory separators | Worked | Still works — separators kept literal |
| Path containing only normal ASCII | Worked | Unchanged behavior |

## Net effect on tonight's failure mode

`guestrin-lab/deepscholar` had one doc file whose path contained `\n` at position 177. With this PR, the `\n` entry is dropped at `_list_doc_files` and the rest of the repo's doc files (presumably normal `.md` files) are inventoried successfully. Operator can re-run `tools/finish_stage1.py` against the `bulk-20260514T042627Z` run after merge to confirm the repo lands in `'inventoried'` state.

## Out of scope (per LLD)

* Schema changes (none needed).
* Re-running Stage 1 against the affected repo — operator-driven follow-up.
* Path filtering by repo language or doc-format heuristics.
* Anything affecting `_fetch_raw`'s timeout / retry / stealth behavior.
