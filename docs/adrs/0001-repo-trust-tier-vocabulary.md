# ADR-0001: repo-trust tier vocabulary and promotion rules

**Status:** Accepted
**Date:** 2026-07-28
**Issue:** #333 (umbrella: #241)

## Context

`repo_trust.trust_level` decides how deep a fix we are willing to offer a repo: a repo we have never engaged gets only high-confidence tier-1 fixes, while one that has merged our work can be offered more. The state machine was implemented across #182 / #333 but never written down, so the vocabulary existed only in code and in log strings — and #333's own issue body proposed *different* names than the ones that shipped. This ADR fixes the vocabulary as-built and records why.

## Decision

### The states

| Level | Meaning | Set by |
|---|---|---|
| `new` | No campaign PR has ever been submitted. Implicit default for repos with no trust row. | — |
| `tier1_pending` | We have submitted at least one PR; no merge yet. | `update_trust_on_submit` |
| `tier1_proven` | The maintainer has merged at least one of our PRs. | `_update_trust_on_merge` |
| `tier2_eligible` | ≥14 days have passed since the first merge. | `upgrade_tier1_proven_repos`, during `metrics refresh` |

Transitions are monotonic — trust is never downgraded. `update_trust_on_submit` explicitly refuses to move `tier1_proven` or `tier2_eligible` back to `tier1_pending`; subsequent merges bump `total_merges` without re-promoting.

### Consumer

`pipeline/graph.py` is the only reader of the level: repos at `new` or `tier1_pending` have tier-2 (lower-confidence) fixes filtered out. `tier1_proven` and `tier2_eligible` receive the unfiltered set.

### Divergence from #333's proposal

The issue proposed `tier1_pending → tier2_engaged → tier3_repeat`, with the top tier gated on a **merge count** (N≥2, default 3). The shipped machine instead uses `tier1_proven → tier2_eligible` gated on **elapsed time** (14 days since first merge). We keep the shipped form:

- **The time gate is the better policy for this campaign.** The risk being managed is looking like an automated contributor who piles work onto a maintainer. A cooling-off period after the first merge addresses that directly; a merge-count threshold does not, and is unreachable for most repos (one link fix is all we have to offer, so a second merge may never come — `tier3_repeat` would be dead state).
- **The names are already in production data.** Renaming means a data migration over live `trust_level` strings for a purely cosmetic gain.
- **The semantics the issue asked for are present**, just under different names: "first merge graduates the repo" is `tier1_proven`, and "eligible for deeper investment" is `tier2_eligible`.

### Blacklist is orthogonal to trust

A merge promotes trust **even if the repo is blacklisted**. This is deliberate, and diverges from #333's acceptance line "merge events after blacklist → ignored":

- Submission is gated by the blacklist **table** (`is_blacklisted(repo_url, maintainer)`) at preflight hard gate #3, at `n0_load_target`, and in the batch engine. A blacklisted repo cannot receive a PR regardless of its trust level, so promoting trust cannot cause an unwanted submission.
- The common blacklist reason is `unresponsive` (30 days without a response) and it **expires**. If such a repo later merges our PR, the blacklist was simply stale — suppressing the promotion would discard the strongest positive signal the campaign can receive.
- Trust answers "how deep a fix may we offer?"; the blacklist answers "may we approach at all?". Coupling them would give one concern two enforcement points, and the weaker one would eventually drift.

`repo_trust.is_blacklisted` (the column) has **no readers anywhere in `src/`** — it is vestigial and must not be mistaken for the enforcement path. Removal is tracked separately.

## Consequences

- The vocabulary has one written home; log strings and docstrings are not the spec.
- `check_tier2_eligibility`'s 14-day constant is policy, not arithmetic — changing it is an ADR amendment, not a refactor.
- Anyone adding a fifth state must extend `pipeline/graph.py`'s filter, which currently enumerates the *untrusted* levels (`new`, `tier1_pending`) rather than the trusted ones — a new untrusted state defaults to trusted if that list is not updated. Tests pin the current four.
