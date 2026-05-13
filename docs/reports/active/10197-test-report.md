# Test Report: #197 redirect-equivalence suppression

## Local verification

`poetry run python -m pytest --timeout=120 -q` → **1807 passed, 1 skipped**.

Net test count unchanged: one test in `TestRedirectCandidate` was renamed and updated in place (`test_redirect_chain_short_circuits` → `test_redirect_chain_suppressed_when_original_reachable`).

## RED → GREEN

Pre-change: `test_redirect_chain_short_circuits` asserted a REDIRECT_CHAIN candidate was emitted. After the assertion was flipped to "no candidate, log mentions suppression", the test failed (impl still emitted). After the impl change in `link_detective.py`, the test passes.

## Lint + format

`ruff check . && ruff format --check .` — clean after a one-file reformat.

## Coverage

The investigate() step-4 branch is covered by:

- `test_redirect_chain_suppressed_when_original_reachable` — chain present, suppression logged, candidate empty.
- Other `TestInvestigateReturnsReport` / `TestArchiveMiss` / `TestNoCandidates` tests exercise the surrounding pipeline without depending on REDIRECT_CHAIN emission.

≥95% on changed lines.

## Behavior preserved

Other tests confirm:
- `TestCandidateSorting.test_candidates_sorted_descending` — sorting still works (uses mutation + archive candidates).
- `TestArchiveMiss.test_archive_miss_continues_investigation` — archive-miss path unchanged.
- Trust-tier and signals tests reference `InvestigationMethod.REDIRECT_CHAIN` as an enum, not via emission. Unaffected.

## Out of scope

- Removing REDIRECT_CHAIN from `InvestigationMethod` entirely. Existing DB rows / archived reports reference it. Leave for back-compat.
- Sites that return 30x to a redirect-to-itself loop. `follow_redirects` already has a visited-set guard.
