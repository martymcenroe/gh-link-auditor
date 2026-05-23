# Test Report: #265 logger silencing not taking effect in Stage 3 tools

## Verification path

This bug is a structural import-order problem, not a logic bug. Unit tests aren't a clean fit; the fix is verified by:

1. **Diagnostic probe** that reproduces the original failure and confirms the fix
2. **Live restart of Stage 3** by the operator post-merge (already confirmed in-session: "the spam is gone")
3. **Full suite regression check**: 2158 passed, 1 skipped — no behavioral change to anything under test

### Probe — before the fix

`probe_log_silence.py` (not committed; diagnostic only). Mirrors `finish_stage3.py`'s import + silencing order *without* the eager-import block:

```
=== after import (before silencing) ===
level: 0 (NOTSET)
propagate: True
handlers: 0
```

`setup_logging("archive_client")` NEVER ran during the imports because the LinkDetective chain is lazy. Logger has no handlers, propagate=True (default).

### Probe — after the fix

With the eager imports applied:

```
=== after eager imports (before silencing) ===
level: 20 (INFO)
propagate: False
handlers: 2
```

`setup_logging` ran for all 5 modules. Then `setLevel(ERROR)` actually has something to override:

```
=== after silencing ===
level: 40 (ERROR)
effectiveLevel: 40 (ERROR)

--- WARNING (should be SUPPRESSED): (nothing printed)
--- ERROR (should APPEAR): 2026-05-23T... | ERROR | archive_client | TEST_ERR
```

WARNING is suppressed; ERROR passes. Exactly the contract.

### Live restart

The operator restarted Stage 3 with `poetry run python tools/finish_stage3.py --workers 32` after the working-tree edit. Their console output went from ~50-100 archive_client WARNINGs/sec drowning the per-minute status line to clean status lines only. Confirmed in-session.

### Suite regression

```
$ poetry run pytest -q --tb=line
2158 passed, 1 skipped, 1 warning in 149.29s
```

Same count as post-#266. No test touched.

## Lint + format

```
$ ruff check tools/finish_stage1.py tools/finish_stage2.py tools/finish_stage3.py \
    tools/detect_languages.py src/gh_link_auditor/bulk_scan/host_blocklist.py
All checks passed!
```

ruff combined the 5 individual `from gh_link_auditor import X` lines into one parenthesized block per its import-organization rule. `# noqa: E402` on the opening `(` suppresses the "import not at top of file" warning that the `sys.path` insert above triggers (same noqa pattern as the existing `from gh_link_auditor.bulk_scan import ...` lines that already had `# noqa: E402`).

## CI verification

Standard gate: Test, Lint, auto-review, pr-sentinel. The tools are not imported by the package or by tests, so CI's `pytest` collection won't touch them — Lint catches any import/syntax breakage.

## What's NOT tested

- A unit test that imports `finish_stage3.py` and asserts the resulting logger state. Doable but brittle — the script has `_PROJECT_ROOT` resolution via `Path(__file__).resolve().parent.parent`, sys.path inserts, and a `main()` guard that argparse would block. A subprocess-based test would work but is heavy for the value.
- The other six untracked tools (probes, `derive_host_blocklist.py`, etc.) — out of scope; #258 phase 1.
- `setup_logging`'s "always reconfigure" semantic — possibly worth a separate ticket if it causes friction elsewhere.

## Risk

Structural change with no behavior change to library code. The only failure mode is a future maintainer deleting the eager imports thinking they're unused (the `# noqa: F401` is documentation; the comment block above the import explains why). The fix is verifiable by running any of the four tools and observing the absence of CDX warnings between status lines.
