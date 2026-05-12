---
repo: martymcenroe/gh-link-auditor
issue: 20
url: https://github.com/martymcenroe/gh-link-auditor/issues/20
fetched: 2026-02-17T01:39:57.618839Z
---

# Issue #20: Cheery Littlebottom — Dead Link Detective (Replacement URL Discovery)

# Cheery Littlebottom — Dead Link Detective (Replacement URL Discovery)

## User Story
As a **link rot scanner operator**,
I want **dead links to be automatically investigated for replacement URLs**,
So that **I get actionable fix suggestions instead of just a list of broken links**.

## Objective
Investigate confirmed dead links using archival lookups, redirect detection, URL pattern heuristics, and GitHub API queries to produce a forensic report with candidate replacement URLs ranked by confidence.

## Metadata
- **Effort Estimate:** L (Large) — multiple API integrations, edge cases, caching layer, and comprehensive test suite
- **Budget:** $0 / Free Tier API Usage only.
- **Labels:** `feature`, `module:cheery`

## UX Flow

### Scenario 1: Dead Link with Archive Hit and Redirect Found
1. Scanner confirms `https://example.com/docs/v1/setup` returns 404
2. Cheery queries the Internet Archive CDX API — finds a snapshot from 2025-11-15
3. Cheery extracts the archived page title: "Project Setup Guide"
4. Cheery follows the original URL — discovers a 301 redirect chain to `https://example.com/docs/v2/setup`
5. Cheery confirms the redirect target is live (200 OK)
6. Forensic report: one candidate with method `redirect_chain`, similarity 0.95+
7. Report is passed to the confidence evaluator for final judgment

### Scenario 2: Dead Link with No Archive, No Redirect
1. Scanner confirms `https://defunct-project.io/api-reference` returns DNS failure
2. Cheery queries the Internet Archive — no snapshots found
3. Cheery attempts redirect detection — DNS resolution fails entirely
4. Cheery has no page title to search with — investigation terminates
5. Forensic report: zero candidates, investigation log documents each failed step
6. Report explicitly states "no candidates found" — Cheery does not fabricate evidence

### Scenario 3: GitHub Repository Renamed or Transferred
1. Scanner confirms `https://github.com/old-org/old-repo/blob/main/README.md` returns 404
2. Cheery detects this is a GitHub URL and queries the GitHub API: `GET /repos/old-org/old-repo`
3. GitHub returns 301 with new location: `https://github.com/new-org/new-repo`
4. Cheery reconstructs the full file URL and confirms it's live
5. Forensic report: one candidate with method `github_api_redirect`, similarity 1.0

### Scenario 4: Page Moved Within Same Domain (URL Pattern Heuristics)
1. Scanner confirms `https://docs.project.io/guide/installation` returns 404
2. Cheery queries the Internet Archive — finds snapshot with title "Installation Guide"
3. No redirect chain found
4. Cheery constructs candidate URLs from the archived title and domain using URL slugification patterns:
   - Convert title to kebab-case: `installation-guide`
   - Try standard path patterns: `/docs/installation-guide`, `/getting-started/installation`, `/guide/installation-guide`
   - Try path segment variations: swap `/guide/` for `/docs/`, `/tutorials/`, `/getting-started/`
5. Cheery probes each candidate URL and finds `https://docs.project.io/getting-started/installation` returns 200 OK
6. Cheery fetches the live page content and computes text similarity against the archived content summary
7. Forensic report: one candidate with method `url_heuristic`, similarity 0.82

### Scenario 5: Rate Limiting and Caching
1. Scanner passes 50 dead links to Cheery in a batch
2. Cheery checks the state database — 12 links were already investigated in a previous run
3. Cheery returns cached results for the 12, investigates the remaining 38
4. Rate limiting applies backoff between Internet Archive and GitHub API calls
5. All 50 forensic reports are returned

## Requirements

### Investigation Pipeline
1. Accept a confirmed dead link (URL + HTTP status or error type) as input
2. Execute investigation methods in priority order: redirect detection → archive lookup → URL pattern heuristics → GitHub heuristics
3. Short-circuit early when a high-confidence candidate (similarity ≥ 0.95) is found via redirect
4. Return a structured forensic report for every investigated link, including when no candidates are found
5. Log each investigation step in the `investigation_log` array for auditability

### Internet Archive Integration
1. Query the CDX API (`https://web.archive.org/cdx/search/cdx`) for the dead URL
2. Request the most recent available snapshot (sort by timestamp descending, limit 1)
3. Fetch the archived page HTML from the Wayback Machine snapshot URL
4. Extract the page `<title>` and first 500 characters of visible text content
5. Handle CDX API returning empty results (no snapshots) without error

### Redirect and URL Mutation Detection
1. Follow HTTP redirect chains (301, 302, 307, 308) up to a maximum of 10 hops
2. Record the full redirect chain in the investigation log
3. Test common URL mutations: `/docs/` ↔ `/documentation/`, `/v1/` ↔ `/v2/` ↔ `/v3/`, trailing slash presence/absence
4. Check if the base domain itself redirects (e.g., `old-project.io` → `new-project.dev`)
5. Verify each candidate URL is live (returns 2xx) before including it in the report

### URL Pattern Heuristics
1. If an archived page title is available, construct candidate URLs by slugifying the title (convert to kebab-case) and appending to the original domain under common path prefixes (e.g., `/docs/`, `/guide/`, `/getting-started/`, `/tutorials/`, `/blog/`)
2. If the original URL contained versioned path segments (e.g., `/v1/`), generate variants with incremented versions (`/v2/`, `/v3/`, `/latest/`)
3. Swap known equivalent path segments: `/docs/` ↔ `/documentation/`, `/guide/` ↔ `/guides/`, `/tutorial/` ↔ `/tutorials/`
4. Probe each constructed candidate URL for liveness (HTTP HEAD, fall back to GET on non-2xx)
5. Return a maximum of 3 candidates from URL pattern heuristics
6. Compute a text similarity score (0.0–1.0) between the archived content summary and the candidate page content for each live candidate
7. **No search engine scraping.** All candidate URLs are constructed programmatically from domain + title patterns. Search engine integration is explicitly out of scope.

### GitHub-Specific Heuristics
1. Detect GitHub URLs by domain (`github.com`, `raw.githubusercontent.com`)
2. For repository URLs, query the GitHub REST API `GET /repos/{owner}/{repo}` to detect renames/transfers (301 response)
3. For file URLs within a repo, reconstruct the file path against the new repo location
4. Respect GitHub API rate limits (use authentication token if available via environment variable, fall back to unauthenticated with lower limits)

### Caching and Rate Limiting
1. Cache investigation results in the state database keyed by dead URL
2. Return cached results for previously investigated URLs without re-querying external services
3. Apply exponential backoff per the project's backoff algorithm for all external HTTP requests
4. Respect `Retry-After` headers from the Internet Archive and GitHub APIs

### Forensic Report Structure
1. Every report includes: `dead_url`, `http_status` (or error type), `investigation` object
2. The `investigation` object includes: `archive_snapshot` (URL or null), `archive_title` (string or null), `archive_content_summary` (string or null), `candidate_replacements` (array), `investigation_log` (array of strings)
3. Each candidate replacement includes: `url`, `method` (one of: `redirect_chain`, `url_mutation`, `url_heuristic`, `github_api_redirect`, `archive_only`), `similarity_score` (float 0.0–1.0), `verified_live` (boolean)
4. Candidates are sorted by `similarity_score` descending

### Confidence Score Guidance
1. `redirect_chain` with verified live target: similarity 0.95–1.0 (high confidence — same content, new location)
2. `github_api_redirect` confirmed by API: similarity 1.0 (canonical redirect)
3. `url_mutation` with verified live target: similarity 0.85–0.95 (structural match, content likely same)
4. `url_heuristic` with content match: similarity 0.5–0.9 (computed via `difflib.SequenceMatcher` against archived content)
5. `archive_only` (snapshot exists but no live replacement found): similarity 0.0 (informational only)

## Technical Approach
- **`src/link_detective.py`:** Core `LinkDetective` class with `investigate(dead_url, http_status) → ForensicReport` method orchestrating the pipeline
- **`src/archive_client.py`:** Internet Archive CDX API client using `urllib.request`; parses CDX responses and fetches snapshot HTML
- **`src/redirect_resolver.py`:** Follows redirect chains and tests URL mutations using `urllib.request` with redirect handling disabled (manual follow). **SSRF protection:** Before each connection (including every redirect hop), resolve the target hostname via `socket.getaddrinfo()` and validate the resolved IP against a deny-list of private/reserved ranges. Reject and log before the socket is opened.
- **`src/url_heuristic.py`:** Constructs candidate URLs from domain + archived title patterns using slugification and path variation; no search engine queries
- **`src/github_resolver.py`:** GitHub-specific resolution logic using the REST API; detects renames, transfers, and file moves
- **`src/similarity.py`:** Text similarity scoring using `difflib.SequenceMatcher` (stdlib, no dependencies)
- **HTML parsing:** Optional `beautifulsoup4` for extracting title/content from archived pages; fallback to regex-based extraction if not installed

## Risk Checklist
*Quick assessment - details go in LLD. Check all that apply and add brief notes.*

- [x] **Architecture:** Yes — adds a new investigation subsystem that sits between the scanner and confidence evaluator. Defined interface boundaries: receives dead link confirmation, outputs forensic report.
- [x] **Cost:** Yes — makes external HTTP requests to Internet Archive, GitHub API, and candidate URLs. Mitigated by caching in state database and rate limiting. **Budget: $0 / Free Tier API Usage only.**
- [ ] **Legal/PII:** No PII handled. Dead URLs from scanned documentation are not personal data.
- [x] **Legal/External Data:** Yes — fetches from Internet Archive (CDX API is public, no ToS issues for automated queries with rate limiting) and GitHub API (public API, rate-limited). Respects `robots.txt` is N/A for API endpoints. URL pattern heuristics construct candidate URLs programmatically — no search engine scraping. **Data Processing: Local execution only. No external transmission of scraped content.**
- [ ] **Safety:** No data loss risk. Investigation is read-only — never modifies source files or links. Cached results can be regenerated.

## Security Considerations
- **Input Sanitization:** Dead URLs are validated as well-formed URLs before any HTTP request. Reject URLs with non-HTTP(S) schemes. Sanitize URLs before constructing Internet Archive and GitHub API query strings to prevent injection.
- **Path Validation:** N/A — no local file system operations beyond database caching.
- **Permissions:** Requires outbound HTTP/HTTPS access. Optional `GITHUB_TOKEN` environment variable for authenticated GitHub API access (higher rate limits). Token is read from environment only, never logged or included in reports.
- **SSRF Mitigation:** For every hop in a redirect chain and every candidate URL probe: resolve the target hostname via `socket.getaddrinfo()`, validate the resolved IP address against a deny-list of private/reserved ranges (127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, ::1, fc00::/7), and reject the request **before** initiating the socket connection. Log blocked attempts as "SSRF blocked" in the investigation log.

## Files to Create/Modify
- `src/link_detective.py` — Core investigation orchestrator and `ForensicReport` dataclass
- `src/archive_client.py` — Internet Archive CDX API client
- `src/redirect_resolver.py` — Redirect chain follower and URL mutation tester with pre-connection SSRF validation
- `src/url_heuristic.py` — URL pattern construction from domain + title slugification (replaces search-based heuristics)
- `src/github_resolver.py` — GitHub API rename/transfer detection
- `src/similarity.py` — Text similarity scoring utilities
- `tests/unit/test_link_detective.py` — Unit tests for investigation pipeline with mocked HTTP responses
- `tests/unit/test_archive_client.py` — Unit tests for CDX API response parsing
- `tests/unit/test_redirect_resolver.py` — Unit tests for redirect chain following, URL mutations, and SSRF blocking
- `tests/unit/test_url_heuristic.py` — Unit tests for URL pattern construction and slugification
- `tests/unit/test_github_resolver.py` — Unit tests for GitHub URL detection and API response handling
- `tests/unit/test_similarity.py` — Unit tests for similarity scoring
- `docs/wiki/cheery-littlebottom.md` — Character and subsystem documentation

## Dependencies
- Issue #5 must be completed first (state database for caching investigation results)
- Issue #7 must be completed first (backoff algorithm for rate-limited external requests)

## Out of Scope (Future)
- **Search engine scraping** — no Google/Bing scraping; URL pattern heuristics construct candidate URLs programmatically from domain + title patterns
- **Machine learning similarity** — use `difflib.SequenceMatcher` for MVP; semantic similarity deferred
- **Automatic link replacement in source files** — Cheery investigates and reports; a separate issue handles applying fixes
- **Non-HTTP link types** — mailto:, ftp://, magnet: links are not investigated
- **Paid archive services** — only the free Internet Archive API is used

## Open Questions
- None (all questions resolved)
- [x] Should we scrape search engines for site search? → Resolved: No. Construct candidate URLs from domain + archived title patterns using slugification and path variation to avoid ToS issues. Search engine integration deferred.
- [x] Should `beautifulsoup4` be a required or optional dependency? → Resolved: Optional. Fallback to regex-based `<title>` extraction and naive text extraction if not installed. Document the enhanced capability when BS4 is available.
- [x] What similarity threshold qualifies as a "candidate"? → Resolved: Any score ≥ 0.5 is included in the candidates list. Confidence classification is the evaluator's job, not Cheery's.

## Acceptance Criteria
- [ ] `LinkDetective.investigate()` returns a `ForensicReport` dataclass with all required fields (`dead_url`, `http_status`, `investigation` with `archive_snapshot`, `archive_title`, `archive_content_summary`, `candidate_replacements`, `investigation_log`)
- [ ] When a dead URL has an Internet Archive snapshot, `archive_snapshot` contains a valid Wayback Machine URL and `archive_title` is extracted from the archived HTML
- [ ] When a dead URL returns a 301/302 redirect to a live page, the redirect target appears in `candidate_replacements` with method `redirect_chain` and `verified_live: true`
- [ ] When a GitHub repository URL returns 404 due to rename/transfer, the new repository URL appears in `candidate_replacements` with method `github_api_redirect`
- [ ] When no candidates are found, `candidate_replacements` is an empty array and `investigation_log` contains at least one entry per attempted investigation method
- [ ] `candidate_replacements` are sorted by `similarity_score` descending
- [ ] All candidate URLs with `verified_live: true` return HTTP 2xx at time of investigation
- [ ] Previously investigated URLs return cached results from the state database without making external HTTP requests (verified by mock call count)
- [ ] External HTTP requests use the backoff algorithm from #7 (verified by unit test with mocked 429 responses)
- [ ] URLs with non-HTTP(S) schemes are rejected with a `ValueError` before any network request
- [ ] Redirect chains to private IP ranges (127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) are terminated and logged as "SSRF blocked" in `investigation_log`, with DNS resolution and IP validation performed **before** initiating the socket connection for every hop
- [ ] URL pattern heuristics construct candidate URLs programmatically from domain + title slugification — no search engine queries are made (verified by absence of search engine domains in mock call log)
- [ ] URL pattern heuristics return a maximum of 3 candidates
- [ ] Unit tests pass with all external HTTP calls mocked (no real network requests in tests)

## Definition of Done

### Implementation
- [ ] Core feature implemented
- [ ] Unit tests written and passing

### Tools
- [ ] Update/create relevant CLI tools in `tools/` (if applicable)
- [ ] Document tool usage

### Documentation
- [ ] Update wiki pages affected by this change
- [ ] Update README.md if user-facing
- [ ] Update relevant ADRs or create new ones
- [ ] Add new files to `docs/0003-file-inventory.md`

### Reports (Pre-Merge Gate)
- [ ] `docs/reports/{IssueID}/implementation-report.md` created
- [ ] `docs/reports/{IssueID}/test-report.md` created

### Verification
- [ ] Run 0809 Security Audit - PASS
- [ ] Run 0817 Wiki Alignment Audit - PASS (wiki page created)

## Testing Notes
- **Mocking strategy:** All external HTTP calls (Internet Archive, GitHub API, candidate URLs) must be mocked in unit tests. Use `unittest.mock.patch` on `urllib.request.urlopen`.
- **Archive hit scenario:** Mock CDX API to return a valid response line, mock snapshot fetch to return HTML with a known `<title>` tag. Verify `archive_title` matches.
- **Archive miss scenario:** Mock CDX API to return empty response. Verify `archive_snapshot` is `null` and investigation continues to next method.
- **Redirect chain:** Mock `urlopen` to raise `HTTPError` with 301 status and `Location` header for first call, return 200 for second call. Verify chain is recorded in `investigation_log`.
- **SSRF blocking (pre-connection validation):** Mock `socket.getaddrinfo()` to return a private IP (e.g., `127.0.0.1`) for a redirect target hostname. Verify that `urlopen` is **never called** for that hop (call count = 0 for the blocked URL) and "SSRF blocked" appears in `investigation_log`.
- **URL pattern heuristics:** Mock `urlopen` for constructed candidate URLs. Provide an archived title of "Installation Guide" and verify candidates include slugified paths like `/docs/installation-guide`. Verify no requests are made to search engine domains.
- **GitHub rename:** Mock GitHub API to return 301 with JSON body containing `url` field pointing to new repo. Verify `github_api_redirect` candidate is produced.
- **Cache verification:** Call `investigate()` twice with the same URL. Verify external HTTP mock is called only during the first invocation (call count = expected from first run only).
- **Rate limit retry:** Mock first call to return 429 with `Retry-After: 1`, second call to return 200. Verify backoff is applied and the request succeeds.

---

*"The thing about forensic evidence is that it doesn't lie. It just sits there until someone smart enough comes along to read it."*
— paraphrasing the spirit of **Cheery Littlebottom**, Ankh-Morpork City Watch

---

<sub>**Gemini Review:** APPROVED | **Model:** `gemini-3-pro-preview` | **Date:** 2026-02-16 | **Reviews:** 3</sub>
