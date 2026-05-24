# 10302 - Implementation Report

**Issues:** #302 (C5), #305 (R1), #306 (R2), #307 (R3), #308 (R4), #309 (R5)
**Branch:** `302-preflight-scores-batch2`
**Umbrella:** #281

## Summary

PR-θ: ships C5 (content equivalence, subagent) + the 5 receptivity scores (R1-R5). Brings `CORRECTNESS_SCORES` to 12 callables totaling **100 max points**, so the default threshold of 90 is now actually achievable. Tool A's preflight gate becomes properly meaningful: candidates with sufficient correctness + receptivity now PASS without manual override.

## Scores shipped

| Score | Issue | Rule |
|---|---|---|
| C5 — content equivalence | #302 | subagent `clean=15`, `partial=8`, `unrelated=0`; uncertain/unavailable → soft 8 |
| R1 — stars tiered | #305 | ≥1000=5, ≥500=4, ≥100=3, ≥50=2, ≥20=1, <20=0 |
| R2 — recency tiered | #306 | ≤7d=5, ≤30d=4, ≤90d=3, ≤180d=1, else 0 |
| R3 — outsider PR merge rate | #307 | last 20 closed (author != owner); ≥30%=5, ≥10%=3, >0=1, 0=0; 7d cache via `preflight_pr_stats_cache` |
| R4 — maintainer structure | #308 | org OR ≥2 committers OR CODEOWNERS = 5; solo = 2 |
| R5 — license permissive | #309 | MIT/Apache-2.0/BSD-*/MPL-2.0/ISC = 5; non-permissive = 2; none = 0 |

## Files

### Modified
- `src/gh_link_auditor/preflight/scores.py` — 6 new score functions appended; `_get_repo_meta` helper for cache-aware metadata read; `_r3_score_from_rate` helper for cache-hit / fresh-fetch convergence; `CORRECTNESS_SCORES` registry now has 12 callables
- `tests/unit/preflight/test_scores.py` — `TestCorrectnessScoresRegistry` updated to assert 12 callables; 6 new `TestScore*` classes (29 tests)

## Implementation notes

- **C5 subagent** uses the same `FakeSubagent` pattern as gate #1 / gate #7 (#287). Production uses `RealSubagent` (claude --print). Subagent uncertain → soft 8 (we don't want to escalate just for a soft score; gate #7 / #294 handles the strict "unrelated" case).
- **R3 cache** — reads `preflight_pr_stats_cache` (from #285) before any gh API fetch. Writes after a fresh fetch so subsequent calls within 7 days are instant.
- **R4 composite** — three independent signals (org / multi-committer / CODEOWNERS) any of which awards full 5 pt. Falls back to solo-with-1-committer = 2 pt; only returns 0 on complete fetch failure.
- **`_get_repo_meta` hoisted import** — `fetch_repo_metadata` is now imported at module load (was previously local-scoped inside the helper). Local imports break `monkeypatch.setattr("...scores.fetch_repo_metadata", ...)` because the attribute doesn't exist at module level. Hoisting fixes that.

## Verification

| Check | Result |
|---|---|
| `poetry run pytest -q` | 2407 passed, 1 skipped (was 2378; +29) |
| `poetry run ruff format --check .` + `ruff check .` | clean |
| `git grep banned regex` | 0 hits |
| `CORRECTNESS_SCORES` registry | 12 callables |
| Full point math: 75 + 25 = 100 | yes |

## Scoring is now production-ready

With C5 + R1-R5 wired, tool A's preflight integration produces a real verdict:
- A genuinely-good candidate (alive maintained repo with permissive license + the URL fix that lands correctly) can score 90-100 → PASS
- A weak candidate (low stars OR stale repo OR unfamiliar maintainer) might score 50-80 → SCORE_TOO_LOW, skip
- A bad candidate (corruption, no-op fix, archived repo) trips a hard gate first → HARD_GATE_FAILED

Until the operator runs the E2E verification (#314), the threshold can be tuned via `--preflight-threshold N` on tool A's CLI.

## Out of scope

- #208 fix-stealer diff-equivalence — PR-ζ
- Recorded fixtures + live + golden tests + operator banner — PR-ι
- Donation/sponsorship + dead-domain Google search — PR-κ
- E2E verification of 87 candidates — operator (#314)
