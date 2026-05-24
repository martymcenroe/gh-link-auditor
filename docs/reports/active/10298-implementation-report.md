# 10298 - Implementation Report

**Issues:** #298 (C1), #299 (C2), #300 (C3), #301 (C4), #303 (C6), #304 (C7)
**Branch:** `298-preflight-scores-batch1`
**Umbrella:** #281

## Summary

PR-η: ships 6 of the 7 correctness scores (C1, C2, C3, C4, C6, C7). C5 (content equivalence, subagent) lands in PR-θ along with the 5 receptivity scores (R1-R5).

Wires `CORRECTNESS_SCORES` registry into tool A so `derive_replacement_prs.py` actually runs scoring on every preflight call. The threshold gate (`report.score < args.preflight_threshold`) is now meaningful — candidates that don't score ≥90 get skipped with `preflight_score_<N>` reason.

## Scores shipped

| Score | Issue | Rule |
|---|---|---|
| C1 — URL verbatim | #298 | 10 pt if `dead_url in current_file` |
| C2 — occurrence count | #299 | 10 pt if 1 hit; 5 pt + surface for 2+; 0 if absent |
| C3 — dead HTTP | #300 | 0 if `dead == candidate` (no-op fix); 4xx=10; 5xx=5; None=5 |
| C4 — candidate HTTP | #301 | 200=10; 3xx→final_url shifted=8; 2xx→redirected=8; other=0 |
| C6 — replace simulation valid | #303 | bracket-balance + no orphan `[]()` heuristic |
| C7 — context preserved | #304 | length-delta consistency check: only URL substrings changed |

## Files

### New
- `src/gh_link_auditor/preflight/scores.py` — 6 score functions + `CORRECTNESS_SCORES` registry + shared `_fetch_source_content` helper
- `tests/unit/preflight/test_scores.py` — 6 `TestScoreC*` classes + `TestCorrectnessScoresRegistry` (18 tests)

### Modified
- `tools/derive_replacement_prs.py` — imports `CORRECTNESS_SCORES`; passes `score_components=CORRECTNESS_SCORES` to `run_preflight`
- `tests/unit/tools/test_derive_replacement_prs.py` — extends `_bypass_hard_gates` autouse fixtures in both `TestDeriveAndSubmit` and `TestMain` to also empty `CORRECTNESS_SCORES` (so existing tests stay offline); `TestPreflightIntegration._make_fake_run_preflight` accepts `**kwargs` for forward-compat with new `score_components=` parameter

## Dispatch behavior change

Before PR-η: `run_preflight` returned `score=threshold` whenever `score_components` was empty (PASS by default).

After PR-η: tool A passes `CORRECTNESS_SCORES` so `score_breakdown` is populated. The verdict is now `PASS` when `sum(points_awarded) >= threshold`, else `SCORE_TOO_LOW`. Currently the 6 correctness scores total 60 max; **PR-θ adds C5 (15) + R1-R5 (25) for the full 100 — that's required to reach the 90 threshold reliably**. Until PR-θ lands, scores total ≤ 60 < 90, so production runs will skip every repo with `preflight_score_<N>`.

This is expected and intentional: it surfaces a clear "we're not ready yet" signal until the full scoring is wired. The operator can override with `--skip-preflight` if needed.

## Verification

| Check | Result |
|---|---|
| `poetry run pytest -q` | 2378 passed, 1 skipped (was 2360; +18) |
| `poetry run ruff format --check .` + `ruff check .` | clean |
| `git grep -i -E '(A\+\+\|PRs filed\|contribution graph\|green square\|naked ambition)'` | 0 hits |
| `CORRECTNESS_SCORES` registry | 6 callables |
| Each score has at least one full + one zero/partial test | yes |
| Tool A integration honors empty-registry override (autouse fixtures) | yes |

## Out of scope

- C5 content equivalence (subagent) — PR-θ
- R1-R5 receptivity scores — PR-θ
- Recorded fixtures + live tests — PR-ι
- #208 fix-stealer — PR-ζ
- Donation/sponsorship skip + dead-domain search — PR-κ
- E2E verification (#314) — operator
