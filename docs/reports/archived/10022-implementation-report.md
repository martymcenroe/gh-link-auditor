# Implementation Report: #22 The Clacks Network — LangGraph Pipeline Core (N0–N5)

**Date:** 2026-03-18
**LLD:** LLD-022

## Changes

### New Files
- `src/gh_link_auditor/pipeline/state.py` — PipelineState TypedDict + persistence
- `src/gh_link_auditor/pipeline/graph.py` — LangGraph StateGraph wiring (N0→N1→CB→N2→N3→N4→N5)
- `src/gh_link_auditor/pipeline/circuit_breaker.py` — Volume control (max_links threshold)
- `src/gh_link_auditor/pipeline/cost_tracker.py` — LLM cost estimation per model
- `src/gh_link_auditor/pipeline/nodes/n0_load_target.py` — Repo validation and doc file listing
- `src/gh_link_auditor/pipeline/nodes/n1_scan.py` — Dead link discovery via URL extraction + check_url
- `src/gh_link_auditor/pipeline/nodes/n2_investigate.py` — LinkDetective wrapper for candidate discovery
- `src/gh_link_auditor/pipeline/nodes/n3_judge.py` — Slant scorer integration for verdicts
- `src/gh_link_auditor/pipeline/nodes/n4_human_review.py` — Terminal HITL for low-confidence verdicts
- `src/gh_link_auditor/pipeline/nodes/n5_generate_fix.py` — Unified diff patch generation
- `src/gh_link_auditor/cli/run.py` — CLI subcommand for single-repo pipeline
- Tests: full test suite in `tests/unit/pipeline/`

### Modified Files (coverage closure)
- `tests/unit/pipeline/test_n5.py` — +1 test: same-URL replacement returns empty diff (line 58)

## Deviations from LLD
- None

## Test Count
- Before: 1078 tests
- After: 1079 tests (+1 coverage gap test)
