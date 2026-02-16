# Issue Review: Cheery Littlebottom — Dead Link Detective (Replacement URL Discovery)

## Identity Confirmation
I am Gemini 3 Pro, acting as Senior Technical Product Manager & Governance Lead.

## Pre-Flight Gate
PASSED

## Review Summary
This is an exceptionally detailed and well-structured specification. It clearly anticipates security risks (SSRF, Input Sanitization) and Legal constraints (Privacy, Scraping). However, there is a direct contradiction between the **Requirements** and the **Out of Scope** sections regarding "Search Heuristics" which must be resolved to prevent accidental implementation of prohibited scrapers.

## Tier 1: BLOCKING Issues
No blocking issues found. Issue is actionable subject to Tier 2 fixes.

### Security
- [ ] No issues found. Strong SSRF and Input Sanitization controls are already present.

### Safety
- [ ] No issues found.

### Cost
- [ ] No issues found. Budget is clearly defined ($0) and relies on caching/rate-limiting.

### Legal
- [ ] No issues found. Data residency and scraping limitations are explicitly defined.

## Tier 2: HIGH PRIORITY Issues

### Quality
- [ ] **Specification Contradiction (Search Heuristics):**
    - **Issue:** The **Requirements > Search Heuristics** section describes constructing a `site:{domain} "{title}"` query and returning "top 3 search-derived candidates." This implies using a search engine index. However, **Out of Scope** and **Open Questions** explicitly ban "search engine scraping" and state the logic should be "Construct candidate URLs from domain + title patterns."
    - **Recommendation:** Rewrite **Requirements > Search Heuristics** to remove references to `site:` queries and "search results." Replace with specific "URL Fuzzing/Slugification" logic (e.g., "Convert archived title to kebab-case and append to domain", "Try standard paths like /docs/{title-slug}").

### Architecture
- [ ] **SSRF Implementation Detail:**
    - **Issue:** The Technical Approach mentions using `urllib.request`. The Acceptance Criteria requires blocking redirects to private IPs (SSRF). Standard `urllib` does not easily allow IP inspection *before* connection during a redirect chain.
    - **Recommendation:** Add a specific implementation note or AC to "Resolve DNS and validate IP against deny-list *before* initiating the socket connection for every hop in the redirect chain."

## Tier 3: SUGGESTIONS
- Add label: `feature`
- Add label: `module:cheery`
- In `src/link_detective.py`, consider defining the "Confidence Score" logic strictly (e.g., 1.0 for API confirmed, 0.9 for Content Match, 0.5 for URL heuristic) so the Evaluator (downstream) has consistent inputs.

## Questions for Orchestrator
1. None.

## Verdict
[ ] **APPROVED** - Ready to enter backlog
[x] **REVISE** - Fix Tier 1/2 issues first
[ ] **DISCUSS** - Needs Orchestrator decision