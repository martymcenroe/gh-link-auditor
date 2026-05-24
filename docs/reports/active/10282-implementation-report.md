# 10282 - Implementation Report

**Issues:** #282 (LLD), #315 (network final_url), #316 (RepoQuality fields)
**Branch:** `282-lld-and-prereq-extensions`
**Worktree:** `gh-link-auditor-282`
**Umbrella:** #281 (Phase B preflight)

## Summary

PR-α of the Phase B preflight execution plan. Ships:

1. The design doc (LLD-281) capturing the full Phase B feature in the repo's public LLD surface — including the `claude --print` subagent invocation pattern (the universal-CLAUDE-md-mandated alternative to the Claude Code session-only Agent tool).
2. Two small source extensions that subsequent gate / score implementations depend on:
   - `network.RequestResult.final_url` for redirect-aware preflight (gate #7 / #294 + score C4 / #301).
   - `RepoQuality.{archived, disabled, license}` for archived/disabled gating (gate #2 / #289) and license scoring (R5 / #309).

No new behavior is exposed; the extensions are passive — they only add a key / fields that nothing reads yet.

## Files

### New
- `docs/lld/active/LLD-281.md` — full Phase B design doc; mirrors the LLD-036 format

### Modified
- `src/gh_link_auditor/network.py`
  - `RequestResult` TypedDict gets `final_url: NotRequired[str | None]` (kept `NotRequired` so existing call sites that build `RequestResult` dicts without this key remain valid)
  - `_make_request` returns a 5-tuple now (added `final_url`); pulls `response.url` (or `exc.url`) when a response was received, `None` on connection-level failures
  - `check_url` propagates `final_url` into all 3 `RequestResult` constructions (success / permanent failure / retry-exhausted)
  - `_headless_browser_get` populates `final_url` from `page.url` after navigation; defensive `getattr(page, "url", None)` so the existing test fakes that don't expose `url` keep working
- `src/gh_link_auditor/repo_quality.py`
  - `RepoQuality` dataclass gets `archived: bool = False`, `disabled: bool = False`, `license: str | None = None`
  - `fetch_repo_metadata` jq query extended to surface `.archived`, `.disabled`, `.license.spdx_id`
- `tests/fakes/http.py`
  - `FakeURLResponse` accepts a `url` parameter (default `None`) and exposes it as the `.url` attribute — matches the urllib response API
- `tests/unit/test_network.py`
  - 3 `TestMakeRequestEdgeCases` tests updated to unpack the new 5-tuple
  - `TestCheckUrlFullFlow::test_check_url_default_configs` keyset assertion extended with `final_url`
  - NEW `TestCheckUrlFinalUrl` class: 5 tests covering direct 2xx, redirect target, fallback to requested URL, DNS failure (None), HTTPError carrying url
- `tests/unit/test_repo_quality.py`
  - `TestFetchRepoMetadata::test_fetches_stars_and_pushed_at` updated to include the new jq fields (backward-compat sanity)
  - NEW `TestFetchRepoMetadataExtended` class: 5 tests covering archived / disabled / license SPDX / missing license / missing-keys defaults

## Verification

| Check | Result |
|---|---|
| `git grep -i -E '(A\+\+\|PRs filed\|contribution graph\|green square\|naked ambition)'` | 0 hits (Phase A still clean) |
| `poetry run pytest -q` | 2247 passed, 1 skipped (was 2237 before; +10 from new tests) |
| `poetry run ruff format --check .` | 234 files already formatted |
| `poetry run ruff check .` | All checks passed |
| `LLD-281.md` exists | Yes; references all 33 sub-issues + 2 prereqs |
| `final_url` populated in `check_url` success path | Yes (covered by `test_final_url_matches_requested_when_no_redirect`) |
| `final_url` reflects redirect target | Yes (covered by `test_final_url_reflects_redirect_target`) |
| `RepoQuality.archived` / `.disabled` / `.license` populated | Yes (covered by `TestFetchRepoMetadataExtended`) |

## Out of scope (deferred to subsequent PRs)

- Actual preflight tool (`tools/preflight_check.py`) — PR-β scaffolds it
- Cache tables — PR-β
- Subagent infrastructure — PR-β
- Tool A integration — PR-γ
- Hard gates — PR-δ / ε
- Score components — PR-η / θ
- Recorded-fixture + live tests — PR-ι
- E2E verification of 87 candidates — #314, deferred for operator review

## Operator decisions reflected in LLD

- Stars floor: 20
- Threshold: 90/100
- Subagent mode: `claude --print` with `CLAUDECODE=""` (per universal CLAUDE.md mandate; supersedes the issue body's "Agent tool" wording, which is Claude-Code-session-only)
- Outsider PR merge rate: 7-day cache
- Live URL re-verification: PRIOR TO FORK, mandatory
- Multi-occurrence dead URL: flag + surface (don't refuse)
- Real testing: NO MagicMock, `tests/fakes/` patterns
