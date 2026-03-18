# Implementation Report: #21 Mr. Slant — Scoring Engine & HITL Dashboard

**Date:** 2026-03-18
**LLD:** LLD-021

## Changes

### New Files
- `src/slant/scorer.py` — Multi-signal scoring engine with tier classification
- `src/slant/config.py` — Default signal weights (redirect=40, title=25, content=20, url_path=10, domain=5)
- `src/slant/models.py` — TypedDicts: Verdict, ScoringBreakdown, ForensicReportEntry, CandidateEntry, VerdictsFile
- `src/slant/dashboard.py` — Single-file HTTP server (localhost:8913) with side-by-side iframes
- `src/slant/cli.py` — CLI entry point with `score` and `dashboard` subcommands
- `src/slant/signals/redirect.py` — Redirect chain signal (weight=40)
- `src/slant/signals/title.py` — Title match signal (weight=25)
- `src/slant/signals/content.py` — Content similarity signal (weight=20)
- `src/slant/signals/url_path.py` — URL path similarity signal (weight=10)
- `src/slant/signals/domain.py` — Domain match signal (weight=5)
- `tests/unit/test_scorer.py` — Scorer unit tests
- `tests/unit/test_dashboard.py` — Dashboard unit tests
- `tests/unit/test_signals.py` — Signal module unit tests

### Modified Files (coverage closure)
- `tests/unit/test_dashboard.py` — +2 tests: atomic write error cleanup (lines 64-66), KeyboardInterrupt shutdown (lines 335-336)
- `tests/unit/test_scorer.py` — +1 test: write_verdicts error cleanup (lines 229-231)
- `tests/unit/test_signals.py` — +2 tests: redirect loop (line 82), empty stripped content (line 93)
- `tests/unit/test_auth.py` — ruff format fix (pre-existing)

## Deviations from LLD
- None

## Test Count
- Before: 1066 tests
- After: 1071 tests (+5 coverage gap tests)
