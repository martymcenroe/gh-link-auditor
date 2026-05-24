# 10243 - Implementation Report

**Issues:** #243 (donation skip), #213 (dead-domain Google search)
**Branch:** `243-nice-to-haves`
**Umbrella:** N/A — both are standalone "nice-to-haves before scaling" from the paranoid triage

## Summary

PR-κ: ships the 2 paranoid-triage nice-to-haves. Both are small false-positive-reduction work that improves the operator's signal-to-noise upstream of preflight.

## #243 — Donation / sponsorship URL categorical skip

Donation URLs (Patreon, Ko-fi, GitHub Sponsors, etc.) are intentional support links the maintainer placed. They sometimes return 4xx (auth-required, campaign paused, account closed, account moved), but "fixing" them would break the maintainer's revenue link. Categorical skip is the right behavior.

- Added `DONATION_DOMAINS` set in `src/gh_link_auditor/false_positives.py` (15 domains)
- Added `_DONATION_PATH_PREFIXES` tuple for path-prefix matches on multi-purpose domains (`github.com/sponsors/`, `paypal.com/donate`, `stripe.com/donate`)
- Added `is_donation_url(url)` predicate with hostname + subdomain-suffix + path-prefix matching, www-prefix normalization
- Wired into the master `is_false_positive` dispatch right after `is_always_alive_domain` (before status-based checks)

## #213 — Skip `site:DOMAIN` queries when domain is dead

`generate_google_searches` (`src/gh_link_auditor/pipeline/nodes/n4_human_review.py`) emits `site:domain.com` queries even when the domain itself is gone (DNS failure, expired cert, whole-domain rebrand). Google returns zero results for dead domains — the operator clicks a useless search and gets no signal.

- Added `dead_domain: bool = False` parameter
- When `dead_domain=True`, skip the `site:{domain}` queries; emit topic + URL-triangulation searches only
- Default behavior unchanged (backward-compatible)

The caller (N4) doesn't yet know whether to set `dead_domain=True` — that signal will come from the failure-class classification work in #261. Until then, the parameter exists with sensible default, ready to wire up.

## Files

### Modified

- `src/gh_link_auditor/false_positives.py` — `DONATION_DOMAINS`, `_DONATION_PATH_PREFIXES`, `is_donation_url`, dispatch in `is_false_positive`
- `src/gh_link_auditor/pipeline/nodes/n4_human_review.py` — `generate_google_searches` accepts `dead_domain` keyword
- `tests/unit/test_false_positives.py` — 5 new tests in `TestIsFalsePositive` for the donation dispatch + new `TestIsDonationUrl` class (9 tests for the predicate)
- `tests/unit/pipeline/test_n4.py` — 3 new tests in `TestGenerateGoogleSearches` covering `dead_domain=True` / `dead_domain=False` / dead-domain with no name

## Verification

| Check | Result |
|---|---|
| `poetry run pytest -q` | 2424 passed, 1 skipped (was 2407; +17) |
| `poetry run ruff format --check .` + `ruff check .` | clean |
| `git grep banned regex` | 0 hits |
| `is_donation_url("https://www.patreon.com/bePatron?u=51974655")` | True |
| `is_donation_url("https://github.com/sponsors/martymcenroe")` | True |
| `is_donation_url("https://github.com/martymcenroe/gh-link-auditor")` | False |
| `generate_google_searches(url, dead_domain=True)` — no `site:` queries | yes |

## Out of scope

- Wiring `dead_domain=True` into N4 callers — requires the failure-class classification from #261
- Subagent-driven domain-rebrand detection — #262
- Phase B preflight (separate PR series, now complete: PR-α through PR-θ)
