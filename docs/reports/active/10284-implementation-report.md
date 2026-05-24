# 10284 - Implementation Report

**Issue:** #284 — `feat(preflight)`: integrate preflight gate into tools/derive_replacement_prs.py
**Branch:** `284-preflight-toola-integration`
**Umbrella:** #281

## Summary

PR-γ: wires `run_preflight()` into `tools/derive_replacement_prs.derive_and_submit` PRIOR to `n6_submit_pr`. No fork, no push, no PR until preflight passes. Adds the 4 promised CLI flags.

The preflight is run per repo (first safe row as the representative candidate). Gate / score implementations (per-issue under #281) refine evaluation later — for now the scaffold returns `PASS` with `score=threshold` so the integration permits submission by default. The gating semantics are real: when actual gates fail, the dispatch routes to the right `skipped` reason.

## Files

### Modified

- `tools/derive_replacement_prs.py`
  - New imports: `PreflightVerdict`, `save_report`, `DEFAULT_REPORT_DIR`, `DEFAULT_THRESHOLD`, `run_preflight`
  - `derive_and_submit` runs `run_preflight()` after the `safe_rows` filter and before `_build_state` + `n6_submit_pr`. Verdict dispatch:
    - `HARD_GATE_FAILED` → skip with `preflight_gate_{report.gate_failure_name}`
    - `NEEDS_OPERATOR_REVIEW` → skip with `preflight_needs_review`
    - `score < threshold` → skip with `preflight_score_{N}`
    - `--preflight-report-only` → skip every repo with `preflight_report_only` (reports still written)
    - `--skip-preflight` → bypass the verdict check; write report with BAD ESCAPE banner; allow N6
  - 4 new flags on `_build_parser`: `--preflight-threshold` (default 90), `--preflight-log-dir` (default `data/preflight-reports/`), `--preflight-report-only`, `--skip-preflight`
- `tools/preflight_check.py`
  - Scaffold `run_preflight` now returns `score=threshold` (was 0) so the integration's threshold check passes by default. Per-gate / per-score issues will set real scores from `score_breakdown` sum
- `tests/unit/tools/test_preflight_check.py`
  - 3 tests updated: `test_returns_preflight_report`, `test_custom_threshold_passed_through`, `test_score_only_prints_int` — assert score == DEFAULT_THRESHOLD (was 0)
- `tests/unit/tools/test_derive_replacement_prs.py`
  - `_make_args` helper extended with `preflight_threshold`, `preflight_log_dir` (tempdir), `preflight_report_only=False`, `skip_preflight=False`
  - `TestBuildParser::test_defaults` + `test_explicit_flags` updated with 4 new flag assertions
  - NEW `TestPreflightIntegration` class — 5 tests:
    - `test_hard_gate_failed_skips_with_gate_name`
    - `test_needs_operator_review_skips`
    - `test_score_too_low_skips_with_score`
    - `test_preflight_report_only_skips_all_without_filing`
    - `test_skip_preflight_bypasses_gate`

## Verification

| Check | Result |
|---|---|
| `poetry run pytest -q` | 2320 passed, 1 skipped (was 2315 after PR-β; +5 from PR-γ integration tests) |
| `poetry run ruff format --check .` | 242 files already formatted |
| `poetry run ruff check .` | All checks passed |
| `poetry run python tools/derive_replacement_prs.py --help` | Lists the 4 new flags + the existing `--campaign-allowed` |

## Design notes

- **Per-repo vs per-candidate.** The scaffold's `run_preflight` signature takes a single candidate, so the integration runs preflight ONCE per repo using `safe_rows[0]` as the representative. When per-gate issues land, they may refine to per-candidate evaluation within a PR. This PR doesn't pre-empt that decision.
- **`--skip-preflight` always writes the report.** The BAD ESCAPE banner in the markdown ensures the operator can see the bypass after the fact, even though the verdict didn't gate.
- **`--preflight-report-only` writes reports + skips submission.** Useful for the #314 end-to-end verification step where the operator wants to read 87 reports without filing 87 PRs.

## Out of scope

- Per-candidate (vs per-repo) preflight evaluation — gate / score issues will decide
- Actual hard gate logic — PR-δ + PR-ε
- Actual score components — PR-η + PR-θ
- Subagent runtime fixture / live tests — PR-ι
- E2E verification (#314) — operator
