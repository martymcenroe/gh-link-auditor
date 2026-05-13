# Implementation Report: #185 classic-PAT fork + cross-fork PR

## Summary

`pipeline/nodes/n6_submit_pr.py` previously used `gh repo fork` and `gh pr create` (cross-fork) via subprocess. Both fail with HTTP 403 when gh CLI is authenticated with a fine-grained PAT (today's setup) — the REST API forbids those operations for fine-grained tokens against arbitrary external repos.

This PR routes both calls through AssemblyZero's `classic_pat_session` (ADR-0216), which decrypts the broader-scope classic PAT in-process via gpg-agent. The PAT lives only in Python heap during the `with` block. Everything else in N6 (clone over HTTPS, git push to your own fork, `gh api` reads of the default branch) keeps working with the fine-grained PAT.

See LLD-185.

## Changes

### `src/gh_link_auditor/classic_pat.py` (NEW)

Lazy-import shim wrapping `AssemblyZero/tools/_pat_session.py`. No imports at module-load time. `classic_pat_session()` adds AssemblyZero's tools dir to `sys.path` and imports the underlying function on first call. CI / machines without AssemblyZero installed get a clear `RuntimeError` only at call time.

### `src/gh_link_auditor/pipeline/nodes/n6_submit_pr.py`

- New module-level constants `_GH_API`, `_GH_API_HEADERS_BASE`, `_GH_API_TIMEOUT_S`.
- `_fork_repo(owner, repo)` rewritten: POSTs to `https://api.github.com/repos/{owner}/{repo}/forks` with the classic PAT in the Authorization header; returns `full_name` from the response body. Idempotent (re-forking returns the existing fork). The previous `gh auth status` parsing + `gh api user` fallback is deleted (the REST response includes `full_name` directly).
- `_create_pr(upstream_owner, upstream_repo, head, base, title, body)` NEW: POSTs to `/repos/{owner}/{repo}/pulls`; returns `(html_url, number)` from the response.
- `n6_submit_pr` orchestration: the inline `_run_gh(["pr", "create", ...])` call is replaced with `_create_pr(...)`. `_run_gh` is still used by `_get_default_branch` and `_clone_fork` (those work fine with the fine-grained PAT).
- 4xx/5xx responses raise `RuntimeError` with a useful message — keeps the outer `n6_submit_pr` exception-handling unchanged (still only catches `RuntimeError` and `subprocess.CalledProcessError`).

### `tests/unit/pipeline/test_n6.py`

- `TestForkRepo` rewritten (3 tests): success path checks the REST response is parsed and the Authorization header carries the classic PAT; 4xx raises; classic-PAT decryption failure propagates.
- `TestCreatePr` NEW (2 tests): success returns `(url, number)` and sends the correct JSON payload; 4xx raises.
- `TestN6SubmitPr.test_happy_path_mocked`, `test_writes_tier1_pending_trust_on_success`, `test_trust_update_failure_does_not_abort_pr` updated to mock `_fork_repo`, `_get_default_branch`, `_create_pr` directly (cleaner than the previous `_run_gh` switch-statement fakes).
- Net change: +3 tests (5 new in TestForkRepo + TestCreatePr, -2 removed from the old gh-CLI-based TestForkRepo).

## Files modified

| File | Change |
|------|--------|
| `src/gh_link_auditor/classic_pat.py` | NEW shim module |
| `src/gh_link_auditor/pipeline/nodes/n6_submit_pr.py` | `_fork_repo` rewrite, new `_create_pr`, orchestration update |
| `tests/unit/pipeline/test_n6.py` | rewrite TestForkRepo, new TestCreatePr, update happy-path mocks |
| `docs/lld/active/LLD-185.md` | NEW design |

## Test count baseline

`pytest --co -q` collects **1798 tests** post-change (was 1795, +3 net from #185).

## Out of scope

- Re-encrypting the classic PAT if scope changes. Operator concern.
- Fallback when AssemblyZero is missing (CI). `n6_submit_pr` is never run in CI; mocked tests cover the unit-test path.
- `gh repo clone` and `git push` (work fine with fine-grained PAT, unchanged).
