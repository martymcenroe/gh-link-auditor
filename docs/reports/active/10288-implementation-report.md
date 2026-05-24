# 10288 - Implementation Report

**Issues:** #288 (anti_ai), #290 (blacklist), #294 (redirect_target)
**Branch:** `288-preflight-gates-batch2`
**Umbrella:** #281

## Summary

PR-ε: ships the 3 remaining hard gates — the subagent-using ones (anti_ai, redirect_target) plus the blacklist gate that exercises the already-plumbed maintainer-level `is_blacklisted(repo_url, maintainer)`. Completes the 10-gate set.

Also wires the dispatch rule that routes a gate result with `reason="needs_operator_review"` to `NEEDS_OPERATOR_REVIEW` verdict (instead of the generic HARD_GATE_FAILED). This is how subagent gates surface uncertain LLM classifications to the operator for manual decision.

## Gates shipped

| Gate | Issue | Failure modes |
|---|---|---|
| `gate_anti_ai` | #288 | subagent `hostile` → fail; subagent `uncertain` → `needs_operator_review` reason; subagent missing → keyword fallback (`ANTI_AI_PHRASES`) hits → `uncertain`; clean fallback → PASS |
| `gate_blacklist` | #290 | `is_blacklisted(repo_url, maintainer)` returns True (either axis) |
| `gate_redirect_target_related` | #294 | candidate URL redirects to unrelated final URL per subagent; pure no-redirect → skip subagent and PASS; defensive PASS on subagent uncertain |

## Files

### Modified
- `src/gh_link_auditor/preflight/gates.py` — added 3 gate functions + appended to `HARD_GATES` (now 10 callables); reads `prompts/preflight/{ai_scan,redirect_target}.txt` via the relative path
- `tools/preflight_check.py` — `run_preflight` dispatch routes `reason == "needs_operator_review"` to `NEEDS_OPERATOR_REVIEW` verdict (rest of dispatch unchanged)
- `tests/unit/preflight/test_gates.py` — 13 new tests; `TestHardGatesRegistry` updated to assert 10 gates

## Subagent integration

Each subagent gate accepts a `subagent` kwarg for injection. Production uses `RealSubagent()` (the `claude --print` wrapper from #287). Tests inject `FakeSubagent.configure(default=...)` to control verdicts deterministically.

Subagent unavailable / errors / `uncertain` verdicts surface defensively:
- `gate_anti_ai`: uncertain → `needs_operator_review` (operator reviews report); subagent missing → keyword fallback (`hostile_classifier.ANTI_AI_PHRASES`); hits → `needs_operator_review`
- `gate_redirect_target_related`: uncertain → defensive PASS (we don't have a non-LLM signal here, so we don't drop the candidate)

## Verification

| Check | Result |
|---|---|
| `poetry run pytest -q` | 2360 passed, 1 skipped (was 2347; +13) |
| `poetry run ruff format --check .` | clean |
| `poetry run ruff check .` | clean |
| `git grep -i -E '(A\+\+\|PRs filed\|contribution graph\|green square\|naked ambition)'` | 0 hits |
| `HARD_GATES` registry | 10 callables |
| `run_preflight` dispatches `needs_operator_review` → NEEDS_OPERATOR_REVIEW | yes |

## Out of scope

- Score components (#298–#309) — PR-η + PR-θ
- #208 fix-stealer (independent) — PR-ζ
- Recorded fixtures (#310) + live (#311) + golden (#312) tests — PR-ι
- Operator-escalation banner refinements (#313) — PR-ι
- E2E (#314) — operator
