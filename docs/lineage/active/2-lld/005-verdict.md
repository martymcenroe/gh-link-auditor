# LLD Review: Issue #2 - Feature: Architect 'Doc-Fix Bot'

## Identity Confirmation
I am Gemini 3 Pro, acting as Senior Software Architect & AI Governance Lead.

## Pre-Flight Gate
PASSED

## Review Summary
The LLD is well-structured with excellent attention to Test Driven Development (TDD) and traceability. The proposed architecture is sound for a Python-based automation tool. However, there are two **Tier 1 Blocking** issues regarding Security (SSRF protection) and Safety (Worktree isolation) that must be addressed before implementation. The Open Questions in Section 1 also require formal resolution.

## Open Questions Resolved
- [x] ~~What is the rate limit strategy for GitHub API across 100+ repos?~~ **RESOLVED: Use exponential backoff on 429s and a conservative hard limit of 500 requests/hour initially.**
- [x] ~~Should we prioritize repos by star count, activity, or random sampling?~~ **RESOLVED: Prioritize by 'least recently scanned'. Star count is irrelevant for maintenance fixes.**
- [x] ~~What is the maximum number of PRs to submit per day (to avoid spam flags)?~~ **RESOLVED: Set hard limit to 10 PRs/day for the pilot phase.**
- [x] ~~Do we need repo owner opt-in/opt-out mechanism (CONTRIBUTING.md check)?~~ **RESOLVED: Yes. Check for `CONTRIBUTING.md` and support a local `blocklist.yaml` for manual opt-outs.**
- [x] ~~Should we track previously submitted PRs to avoid duplicate submissions?~~ **RESOLVED: Mandatory. Use `StateStore` to track (Repo + Link SHA) to prevent duplicate PRs.**

## Requirement Coverage Analysis (MANDATORY)

**Section 3 Requirements:**
| # | Requirement | Test(s) | Status |
|---|-------------|---------|--------|
| 1 | Bot can load and parse 100+ repository targets | 010, 020 | ✓ Covered |
| 2 | Link scanner identifies broken links (404, 410, 403) | 030, 040, 060 | ✓ Covered |
| 3 | Link scanner handles anti-bot responses | 050, 140 | ✓ Covered |
| 4 | Bot executes complete 9-step Git workflow | 070, 120, 130 | ✓ Covered |
| 5 | PRs created with professional messages | 080, 090, 150 | ✓ Covered |
| 6 | State persistence prevents duplicate PRs | 100 | ✓ Covered |
| 7 | Daily execution respects rate limits | 110 | ✓ Covered |
| 8 | Structured reporting (JSON) | 180 | ✓ Covered |
| 9 | GitHub Action runs daily on schedule | 160 | ✓ Covered |
| 10 | Structured logging | 170 | ✓ Covered |

**Coverage Calculation:** 10 requirements covered / 10 total = **100%**

**Verdict:** PASS

## Tier 1: BLOCKING Issues

### Cost
- [ ] No issues found.

### Safety
- [ ] **Worktree Isolation (CRITICAL):** The LLD mentions "Clone/update local fork" but does not explicitly enforce that these operations occur in a simplified `tempfile.TemporaryDirectory()`. Cloning 100+ repos into the bot's own working directory (or a persistent relative path) risks state pollution and disk space issues.
    *   **Recommendation:** Update Section 2.5 and 2.6 to explicitly state that all `git clone` operations occur inside a `tempfile.TemporaryDirectory()` context manager that is cleaned up after each repo processing.

### Security
- [ ] **SSRF Vulnerability (CRITICAL):** The `check_link` function follows URLs found in external repositories. If a repository contains a link to `http://169.254.169.254/latest/meta-data/` (AWS Metadata) or `http://localhost:port`, and the bot runs on cloud infrastructure (GitHub Actions), it could expose environment secrets or internal network topology via the logs or PR description.
    *   **Recommendation:** Add a `validate_ip_safety` check in `link_scanner.py`. The bot MUST resolve the DNS of the target URL and verify it does not point to private/local IP ranges (127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16) *before* making the HTTP request.

### Legal
- [ ] No issues found.

## Tier 2: HIGH PRIORITY Issues

### Architecture
- [ ] No issues found.

### Observability
- [ ] No issues found.

### Quality
- [ ] No issues found. TDD plan is excellent.

## Tier 3: SUGGESTIONS
- **Configurable Timeout:** Ensure the `httpx` client has a strict read timeout (e.g., 10 seconds) to prevent the bot from hanging on "tarpit" servers.
- **User-Agent:** Define a custom User-Agent string in `bot_config.yaml` that includes a contact URL (e.g., `DocFixBot/1.0 (+https://github.com/org/repo)`).

## Questions for Orchestrator
1. None.

## Verdict
[ ] **APPROVED** - Ready for implementation
[x] **REVISE** - Fix Tier 1/2 issues first
[ ] **DISCUSS** - Needs Orchestrator decision