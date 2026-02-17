# LLD Review: #4 - Feature: Add 'Maintainer Policy Check' Module

## Identity Confirmation
I am Gemini 3 Pro, acting as Senior Software Architect & AI Governance Lead.

## Pre-Flight Gate
**PASSED**

## Review Summary
The LLD is well-structured and technically sound. It follows the project's architectural patterns and explicitly defines safety behaviors (Fail-Open). The TDD test plan is comprehensive regarding functional requirements. The design correctly utilizes existing infrastructure (GitHub client, DB connection) without introducing unnecessary dependencies.

## Open Questions Resolved
- [x] ~~Should the bot check for policy files in subdirectories (e.g., `.github/CONTRIBUTING.md`) in addition to root?~~ **RESOLVED: Yes. The bot should check standard GitHub locations (`root`, `.github/`, `docs/`) to respect maintainer conventions.**
- [x] ~~What should the default behavior be if CONTRIBUTING.md doesn't exist? (Current assumption: proceed with scan)~~ **RESOLVED: Proceed with scan (Fail-Open). This ensures the bot remains useful for the majority of repositories that do not have explicit bot policies.**
- [x] ~~Should we support custom policy file locations via configuration?~~ **RESOLVED: No. Stick to GitHub standards for the MVP to maintain simplicity (YAGNI).**

## Requirement Coverage Analysis (MANDATORY)

**Section 3 Requirements:**
| # | Requirement | Test(s) | Status |
|---|-------------|---------|--------|
| 1 | Before scanning a repository, the bot MUST check for a CONTRIBUTING.md file | T010, T140, T150 | ✓ Covered |
| 2 | The bot MUST parse CONTRIBUTING.md for defined policy keywords | T020, T030, T040, T050, T060, T110 | ✓ Covered |
| 3 | If a blocking keyword is found, the bot MUST skip the repository | T070, T130, T160 | ✓ Covered |
| 4 | Blocked repositories MUST be logged in the state database with status 'policy-blacklisted' | T080, T160 | ✓ Covered |
| 5 | The policy check MUST be case-insensitive for keyword matching | T090 | ✓ Covered |
| 6 | If no CONTRIBUTING.md exists, the bot MUST proceed with scanning (fail-open) | T100, T170 | ✓ Covered |

**Coverage Calculation:** 6 requirements covered / 6 total = **100%**

**Verdict:** **PASS**

## Tier 1: BLOCKING Issues
No blocking issues found. LLD is approved for implementation.

### Cost
- [ ] No issues found.

### Safety
- [ ] No issues found.

### Security
- [ ] No issues found.

### Legal
- [ ] No issues found.

## Tier 2: HIGH PRIORITY Issues
No high-priority issues found.

### Architecture
- [ ] No issues found.

### Observability
- [ ] No issues found.

### Quality
- [ ] **Requirement Coverage:** PASS (100%)

## Tier 3: SUGGESTIONS
- **Edge Case Testing:** While Section 7.2 defines a "Fail Open" strategy for API errors (not just missing files), there is no explicit test case for network exceptions (e.g., 500 Internal Server Error). Consider adding a test case like `test_check_policy_api_error_fails_open` to verify the `try/except` block implementation.
- **Caching:** In the future, consider caching policy check results for a short duration (e.g., 24h) to reduce API calls on repeated scans of the same repo.
- **Soft Blocks:** Consider differentiating between `contact-first` (maybe just log a warning) and `no-bot` (hard block). For now, blocking on both is a safe conservative approach.

## Questions for Orchestrator
1. None.

## Verdict
[x] **APPROVED** - Ready for implementation
[ ] **REVISE** - Fix Tier 1/2 issues first
[ ] **DISCUSS** - Needs Orchestrator decision