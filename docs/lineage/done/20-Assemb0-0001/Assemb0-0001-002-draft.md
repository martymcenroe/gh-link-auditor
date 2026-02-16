# Cheery Littlebottom — Dead Link Detective (Replacement URL Discovery)

## User Story
As a **link rot scanner operator**,
I want **dead links to be automatically investigated for replacement URLs**,
So that **I get actionable fix suggestions instead of just a list of broken links**.

## Objective
Investigate confirmed dead links using archival lookups, redirect detection, site search heuristics, and GitHub API queries to produce a forensic report with candidate replacement URLs ranked by confidence.

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

### Scenario 4: Page Moved Within Same Domain
1. Scanner confirms `https://docs.project.io/guide/installation` returns 404
2. Cheery queries the Internet Archive — finds snapshot with title "Installation Guide"
3. No redirect chain found
4. Cheery searches `site:docs.project.io "Installation Guide"` via search heuristics
5. Finds `https://docs.project.io/getting-started/installation` with matching content
6. Forensic report: one candidate with method `site_search`, similarity 0.82

### Scenario 5: Rate Limiting and Caching
1. Scanner passes 50 dead links to Cheery in a batch
2. Cheery checks the state database — 12 links were already investigated in a previous run
3. Cheery returns cached results for the 12, investigates the remaining 38
4. Rate limiting applies backoff between Internet Archive and GitHub API calls
5. All 50 forensic reports are returned

## Requirements

### Investigation Pipeline
1. Accept a confirmed dead link (URL + HTTP status or error type) as input
2. Execute investigation methods in priority order: redirect detection → archive lookup → site search → GitHub heuristics
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

### Search Heuristics
1. If an archived page title is available, construct a `site:{domain} "{title}"` search query
2. If the original domain is entirely dead, broaden the search to the title alone
3. Return the top 3 search-derived candidates maximum
4. Compute a text similarity score (0.0–1.0) between the archived content summary and the candidate page content

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
3. Each candidate replacement includes: `url`, `method` (one of: `redirect_chain`, `url_mutation`, `site_search`, `github_api_redirect`, `archive_only`), `similarity_score` (float 0.0–1.0), `verified_live` (boolean)
4. Candidates are sorted by `similarity_score` descending

## Technical Approach
- **`src/link_detective.py`:** Core `LinkDetective` class with `investigate(dead_url, http_status) → ForensicReport` method orchestrating the pipeline
- **`src/archive_client.py`:** Internet Archive CDX API client using `urllib.request`; parses CDX responses and fetches snapshot HTML
- **`src/redirect_resolver.py`:** Follows redirect chains and tests URL mutations using `urllib.request` with redirect handling disabled (manual follow)
- **`src/github_resolver.py`:** GitHub-specific resolution logic using the REST API; detects renames, transfers, and file moves
- **`src/similarity.py`:** Text similarity scoring using `difflib.SequenceMatcher` (stdlib, no dependencies)
- **HTML parsing:** Optional `beautifulsoup4` for extracting title/content from archived pages; fallback to regex-based extraction if not installed

## Risk Checklist

- [ ] **Architecture:** Yes — adds a new investigation subsystem that sits between the scanner and confidence evaluator. Defined interface boundaries: receives dead link confirmation, outputs forensic report.
- [x] **Cost:** Yes — makes external HTTP requests to Internet Archive, GitHub API, and candidate URLs. Mitigated by caching in state database and rate limiting.
- [ ] **Legal/PII:** No PII handled. Dead URLs from scanned documentation are not personal data.
- [x] **Legal/External Data:** Yes — fetches from Internet Archive (CDX API is public, no ToS issues for automated queries with rate limiting) and GitHub API (public API, rate-limited). Respects `robots.txt` is N/A for API endpoints. Search heuristics use direct URL construction, not scraping search engines.
- [ ] **Safety:** No data loss risk. Investigation is read-only — never modifies source files or links. Cached results can be regenerated.

## Security Considerations
- **Input Sanitization:** Dead URLs are validated as well-formed URLs before any HTTP request. Reject URLs with non-HTTP(S) schemes. Sanitize URLs before constructing Internet Archive and GitHub API query strings to prevent injection.
- **Path Validation:** N/A — no local file system operations beyond database caching.
- **Permissions:** Requires outbound HTTP/HTTPS access. Optional `GITHUB_TOKEN` environment variable for authenticated GitHub API access (higher rate limits). Token is read from environment only, never logged or included in reports.
- **SSRF Mitigation:** Do not follow redirects to private/internal IP ranges (127.x, 10.x, 192.168.x, 172.16-31.x). Validate all candidate URLs resolve to public IPs before fetching.

## Files to Create/Modify
- `src/link_detective.py` — Core investigation orchestrator and `ForensicReport` dataclass
- `src/archive_client.py` — Internet Archive CDX API client
- `src/redirect_resolver.py` — Redirect chain follower and URL mutation tester
- `src/github_resolver.py` — GitHub API rename/transfer detection
- `src/similarity.py` — Text similarity scoring utilities
- `tests/unit/test_link_detective.py` — Unit tests for investigation pipeline with mocked HTTP responses
- `tests/unit/test_archive_client.py` — Unit tests for CDX API response parsing
- `tests/unit/test_redirect_resolver.py` — Unit tests for redirect chain following and URL mutations
- `tests/unit/test_github_resolver.py` — Unit tests for GitHub URL detection and API response handling
- `tests/unit/test_similarity.py` — Unit tests for similarity scoring
- `docs/wiki/cheery-littlebottom.md` — Character and subsystem documentation

## Dependencies
- Issue #5 must be completed first (state database for caching investigation results)
- Issue #7 must be completed first (backoff algorithm for rate-limited external requests)

## Out of Scope (Future)
- **Search engine scraping** — no Google/Bing scraping; search heuristics construct candidate URLs directly from domain + title patterns
- **Machine learning similarity** — use `difflib.SequenceMatcher` for MVP; semantic similarity deferred
- **Automatic link replacement in source files** — Cheery investigates and reports; a separate issue handles applying fixes
- **Non-HTTP link types** — mailto:, ftp://, magnet: links are not investigated
- **Paid archive services** — only the free Internet Archive API is used

## Open Questions
- None (all questions resolved)
- [x] Should we scrape search engines for site search? → Resolved: No. Construct candidate URLs from domain + archived title patterns to avoid ToS issues. Search engine integration deferred.
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
- [ ] Redirect chains to private IP ranges (127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) are terminated and logged as "SSRF blocked" in `investigation_log`
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
- **GitHub rename:** Mock GitHub API to return 301 with JSON body containing `url` field pointing to new repo. Verify `github_api_redirect` candidate is produced.
- **SSRF blocking:** Mock redirect to `http://127.0.0.1/internal` and verify the redirect is not followed and "SSRF blocked" appears in `investigation_log`.
- **Cache verification:** Call `investigate()` twice with the same URL. Verify external HTTP mock is called only during the first invocation (call count = expected from first run only).
- **Rate limit retry:** Mock first call to return 429 with `Retry-After: 1`, second call to return 200. Verify backoff is applied and the request succeeds.

---

*"The thing about forensic evidence is that it doesn't lie. It just sits there until someone smart enough comes along to read it."*
— paraphrasing the spirit of **Cheery Littlebottom**, Ankh-Morpork City Watch