# Test Report: #22 The Clacks Network — LangGraph Pipeline Core (N0–N5)

**Date:** 2026-03-18

## Summary
- Total tests: 1079 passed, 1 skipped
- New tests: 1 (coverage gap closure)

## Coverage (pipeline files)
| File | Before | After |
|------|--------|-------|
| `pipeline/nodes/n0_load_target.py` | 100% | 100% |
| `pipeline/nodes/n1_scan.py` | 100% | 100% |
| `pipeline/nodes/n2_investigate.py` | 100% | 100% |
| `pipeline/nodes/n3_judge.py` | 100% | 100% |
| `pipeline/nodes/n4_human_review.py` | 100% | 100% |
| `pipeline/nodes/n5_generate_fix.py` | 97% | 100% |
| `pipeline/state.py` | 100% | 100% |
| `pipeline/graph.py` | 100% | 100% |
| `pipeline/circuit_breaker.py` | 100% | 100% |
| `pipeline/cost_tracker.py` | 100% | 100% |

## New Test Breakdown

### test_n5.py (+1)
- `test_same_url_replacement_returns_empty`: Replacing URL with itself produces empty unified_diff (line 58)

## Lint/Format
- `ruff check`: clean
- `ruff format`: clean
