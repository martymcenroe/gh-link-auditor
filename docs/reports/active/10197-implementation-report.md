# Implementation Report: #197 suppress redirect-equivalence candidates

## Summary

When the original URL responds with HTTP 30x and the chain ends at a live page, the URL is **reachable** (just redirects). Replacing it with the final URL is a cosmetic canonical-URL update, not a broken-link fix. Today's case: `https://stackoverflow.com/a/14638025` redirects to `https://stackoverflow.com/questions/.../14638025#14638025`. Both URLs work in any browser — the SO short form is intentional.

Previously the pipeline emitted these as REDIRECT_CHAIN candidates with similarity_score=0.98 and short-circuited the rest of N2. Operators saw them in N4 and had to manually reject. Net: HITL noise + no actual fix value.

## Changes

### `src/gh_link_auditor/link_detective.py`

`investigate()` step 4 (REDIRECT_CHAIN) — when `follow_redirects` returns a live final_url:

- **Before**: append a `CandidateReplacement(method=REDIRECT_CHAIN, similarity_score=0.98)`, short-circuit and return early.
- **After**: log "Redirect chain to live final … — original is reachable, candidate suppressed (#197)" and continue to the next investigation method (archive, mutations, etc.).

`follow_redirects` and `verify_live` themselves unchanged — they're still useful for archive-fallback decisions and diagnostics.

### `tests/unit/test_link_detective.py`

`TestRedirectCandidate.test_redirect_chain_short_circuits` renamed to `test_redirect_chain_suppressed_when_original_reachable`. Asserts no REDIRECT_CHAIN candidate is emitted and the suppression message appears in the log.

## What we DON'T change

- The `InvestigationMethod.REDIRECT_CHAIN` enum value stays for backward compatibility (existing DB rows reference it, tier-classification tests still pass).
- `follow_redirects()` still walks chains. Its output is now log-only.
- All other N2 methods unchanged (archive_only, url_mutation, sitemap_search, etc.).

## Files modified

| File | Change |
|------|--------|
| `src/gh_link_auditor/link_detective.py` | suppress REDIRECT_CHAIN candidate emission |
| `tests/unit/test_link_detective.py` | flipped assertion in `TestRedirectCandidate` |
| `docs/lld/active/LLD-197.md` | NEW (just-in-time short design) |

## Test count

1807 (unchanged net — one test renamed/updated in place).

## Operator impact

- python-guide finding #6 (`stackoverflow.com/a/14638025` → long form) and similar short→long redirect "fixes" disappear from N4 review.
- Sites that 30x to a working final (most CDNs, URL shorteners, vanity domains) no longer surface bogus candidates.
- Genuinely-dead URLs unaffected — those don't enter the redirect chain in the first place.
