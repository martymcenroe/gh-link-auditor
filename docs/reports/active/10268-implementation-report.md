# Implementation Report: #268/#269/#270 status-line observability bundle

## Summary

Three small `tools/finish_stage3.py` status-line improvements, bundled because they all touch the same `Stats` class + `render_line()` + `write_status_file()` and ship as one operator-facing surface change:

- **#268** — show yield% + skipped/investigated split inline (do the math the operator was doing in their head)
- **#269** — show recent (5-minute) rate alongside lifetime rate (catch slowdowns the lifetime smooths away)
- **#270** — show time-since-last-candidate (single best "is the pipeline alive?" signal)

## Before / after

**Before:**

```
[10:11:28] stage3 27/107,669 (0.0%) alive=0 lang=0 block=0 no_cand=27 with_cand=0 cands+=0 rate=27/min ETA=66h
```

**After:**

```
[10:11:28] stage3 27/107,669 (0.0%) skipped=0 investigated=27 yield=0.0% cands+=0 rate=27/min (5m: 0/min) ETA=66h last_cand=never
```

Same width-ish; every field is now a decision input.

## Changes

### `tools/finish_stage3.py`

**`Stats` (dataclass):**
- new field `last_cand_monotonic: float | None = None` (#270)
- new field `rate_window: deque` with `maxlen=5` (#269)
- new methods `investigated()`, `skipped()`, `yield_pct()` (#268)
- new methods `recent_rate_per_min()`, `record_rate_sample()` (#269)
- new method `time_since_last_cand_str()` (#270) — formats as `12s` / `8m` / `1.2h` / `never`

**`render_line()`** rewritten:
- `alive=N lang=N block=N` → `skipped=K`
- `no_cand=N with_cand=N` → `investigated=K yield=X.X%`
- `rate=N/min` → `rate=N/min (5m: M/min)`
- new tail `last_cand=Tval`
- `yield=n/a` when no real investigations yet (avoids divide-by-zero)
- `last_cand=never` when no candidate has surfaced yet

**`write_status_file()`** gains keys:
- `recent_rate_per_min`
- `skipped_blocklist` (was previously dropped — bug fix)
- `skipped_total`
- `investigated_total`
- `yield_pct`
- `seconds_since_last_candidate`

**`write_outcome()`:** stamps `stats.last_cand_monotonic = time.monotonic()` when a candidate is recorded.

**`status_emitter()`:** calls `stats.record_rate_sample()` once per tick before rendering, so each printed line uses fresh sample data.

## ASCII discipline

PowerShell on Windows mojibakes em-dash characters. Using `n/a` for "no investigations yet" and `never` for "no candidates yet" instead of `—`. Same convention as #226's avoidance of Unicode box-drawing in CI/Gemini prompts.

## Files modified

| File | Change |
|------|--------|
| `tools/finish_stage3.py` | Stats helpers + render_line + status file format |

No tests added — `Stats` is heavy to import (eager-loads LinkDetective chain), and the math methods are obviously correct. Verified by smoke-test that exercises three states (fresh, mid-run, lots-skipped-no-cand).

## Test count

Unchanged: **2158 passed, 1 skipped** (no test touched).

## Out of scope

- Apply the same observability work to `finish_stage1.py`, `finish_stage2.py`, `detect_languages.py`. They don't have the "candidates" concept, so #270 doesn't apply; #268's yield doesn't either. #269 (recent rate) would help, but each script has a different `Stats` shape. Follow-up if useful.
- Extract `Stats` to a separate module so it's unit-testable without the LinkDetective import chain. Refactor scope creep.
- A multi-line periodic dump (every 5 min, more detail). Different design; possibly useful but the operator's current need is the one-liner being scannable.
