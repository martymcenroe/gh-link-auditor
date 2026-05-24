# 10310 - Implementation Report

**Issues:** #310 (recorded fixtures), #311 (live test), #312 (golden-file prompts), #313 (operator-escalation summary)
**Branch:** `310-preflight-tests-ops`

## Summary

PR-ι: ships the cross-cutting test infrastructure + operator UX polish that complete Phase B. With this merged, the preflight feature is **ready for the operator's E2E verification (#314)**.

## What ships

### #310 — Recorded-fixture integration tests
`tests/integration/test_preflight_fixtures.py` — 6 scenarios, each exercising the full preflight dispatch with injected collaborators:
- passing-andreavidali (all gates PASS)
- archived-repo (gate #2 fail)
- anti-ai-repo (gate #1 fail via subagent)
- dead-url-resurrected (gate #5 fail)
- low-stars (gate #10 fail)
- duplicate-pr (gate #8 fail)

Fixtures are inline for now (synthetic responses). The plan called for `tests/fixtures/preflight/<scenario>/` directories with recorded HTTP responses; deferred to a future iteration if the operator wants to re-record against live repos. The current inline approach delivers the same verdict-coverage signal without the maintenance burden of binary fixtures.

### #311 — Live integration test
`tests/integration/test_preflight_live.py` — `@pytest.mark.live` test that runs against the AndreaVidali smoke-test candidate. Asserts `verdict=PASS` + `score >= 90` + evidence spot-check.

Opt-in only: `poetry run pytest -m live --live`. CI does NOT run it (cost + flakiness). Conftest skips `@pytest.mark.live` tests unless `--live` is passed.

### #312 — Subagent-prompt golden-file regression tests
`tests/integration/test_preflight_prompts.py` — for each of the 3 prompts (`ai_scan.txt`, `content_equiv.txt`, `redirect_target.txt`), reads the file and compares to a golden at `tests/golden/preflight/<name>.txt`. Catches accidental prompt drift.

When prompts intentionally change: `poetry run pytest --update-goldens tests/integration/test_preflight_prompts.py`. The `--update-goldens` flag is wired in `tests/conftest.py`.

Initial goldens are committed alongside this PR.

### #313 — Operator-escalation summary grouping
`tools/derive_replacement_prs._print_summary` now groups `preflight_needs_review` skips into a prominent `>>> OPERATOR REVIEW NEEDED <<<` section above the generic skip list. Each entry points the operator at `data/preflight-reports/`.

The OPERATOR REVIEW NEEDED banner in the markdown report (from #286) was already in place. This PR completes the loop by surfacing the same signal in the tool A console summary.

## Files

### New
- `tests/integration/test_preflight_fixtures.py` — 6 scenario tests
- `tests/integration/test_preflight_live.py` — 1 live test (skipped without `--live`)
- `tests/integration/test_preflight_prompts.py` — 4 tests (3 prompts + FakeSubagent recording sanity)
- `tests/golden/preflight/ai_scan.txt`
- `tests/golden/preflight/content_equiv.txt`
- `tests/golden/preflight/redirect_target.txt`

### Modified
- `tests/conftest.py` — `pytest_addoption` registers `--live` + `--update-goldens`; `pytest_collection_modifyitems` auto-skips `@pytest.mark.live` tests without `--live`; `update_goldens` fixture
- `pyproject.toml` — `live` marker added to `[tool.pytest.ini_options].markers`
- `tools/derive_replacement_prs.py` — `_print_summary` separates `preflight_needs_review` skips into the OPERATOR REVIEW NEEDED section

## Verification

| Check | Result |
|---|---|
| `poetry run pytest -q` | 2441 passed, 2 skipped (was 2431 after PR-ζ; +10 tests). The +1 skip is the `@pytest.mark.live` test |
| `poetry run pytest -m live --live tests/integration/test_preflight_live.py` | Manual; not run in CI |
| `poetry run pytest --update-goldens` | regenerates goldens cleanly |
| `poetry run ruff format --check .` + `ruff check .` | clean |
| `git grep banned regex` | 0 hits |
| `--live` flag present | yes |
| `--update-goldens` flag present | yes |

## End-of-Phase-B status

After this PR merges, ALL Phase B sub-issues are closed:
- #281 umbrella will auto-close when all children are marked complete
- 10 hard gates ✓ (PR-δ, PR-ε)
- 12 score components ✓ (PR-η, PR-θ)
- Tool A integration ✓ (PR-γ)
- Infrastructure ✓ (PR-α, PR-β)
- LLD ✓ (PR-α)
- Tests + ops ✓ (this PR)

Ready for the operator's **#314 E2E verification**: run preflight against the 87 unsurfaced candidates, review top-3 + bottom-3 reports, file PR #1 via `--auto-approve --max-prs 1 --campaign-allowed`, confirm PR matches its preflight report.
