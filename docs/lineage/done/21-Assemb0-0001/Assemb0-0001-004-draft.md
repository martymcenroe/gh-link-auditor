# Mr. Slant — Scoring Engine & HITL Dashboard

## User Story
As a blog maintainer with hundreds of dead links,
I want an automated scoring engine that evaluates candidate replacements and a local dashboard for reviewing uncertain matches,
So that I can efficiently resolve dead links with confidence — auto-approving obvious matches, manually reviewing ambiguous ones, and flagging cases where no good replacement exists.

## Objective
Introduce the Mr. Slant judge module that scores candidate replacement URLs against 5 weighted signals and provides a human-in-the-loop dashboard for reviewing verdicts that fall below the auto-approve threshold.

## UX Flow

### Scenario 1: Scoring a Forensic Report (Happy Path)
1. User runs `python -m slant score --report cheery-report.json`
2. System loads Cheery's forensic report, iterates each dead link and its candidates
3. System computes 5 signal scores per candidate (redirect, title, content, URL path, domain)
4. System writes `verdicts.json` with one verdict object per dead link, including confidence tier
5. Result: User sees summary output — e.g., "12 links scored: 3 AUTO-APPROVE, 6 HUMAN-REVIEW, 2 LOW-CONFIDENCE, 1 INSUFFICIENT"

### Scenario 2: Human Review via Dashboard (Happy Path)
1. User runs `python -m slant dashboard --verdicts verdicts.json`
2. System starts HTTP server on `localhost:8913`
3. User opens browser to `http://localhost:8913`
4. Dashboard displays first HUMAN-REVIEW item: archived snapshot (left iframe) and candidate page (right iframe), with confidence score and scoring breakdown in the header
5. User presses `a` (keyboard shortcut for Approve)
6. Dashboard sends POST to `/api/decide`, updates verdict on disk, advances to next review item
7. Result: All review items decided; dashboard shows summary with counts per decision type

### Scenario 3: Zero Candidates for a Dead Link
1. User runs `python -m slant score --report report-with-empty-candidates.json`
2. System encounters a dead link entry with an empty `candidates` array
3. System produces verdict INSUFFICIENT with confidence 0 and `replacement_url: null`
4. Result: Verdict file reflects the zero-candidate state without error

### Scenario 4: Iframe Load Failure in Dashboard
1. User is reviewing a link in the dashboard
2. The candidate URL returns `X-Frame-Options: DENY`, blocking the iframe
3. Dashboard JavaScript `onerror` handler detects the failure
4. Dashboard displays fallback text panel with archived metadata (title, URL, investigation method) instead of the broken iframe
5. Result: User can still make a decision using the available metadata and the working Archive iframe

### Scenario 5: Invalid API Input
1. An external client or malformed request sends POST to `/api/decide` with `decision: "maybe"`
2. System validates against allowed values (`approved`, `rejected`, `abandoned`, `keep_looking`)
3. System returns HTTP 400 with error message specifying allowed values
4. Result: Verdict file is not mutated; invalid input is rejected

## Requirements

### Scoring Engine
1. Load Cheery's forensic report JSON and iterate all dead link entries
2. For each candidate, compute 5 signal scores with configurable weights (defaults: redirect=40, title=25, content=20, url_path=10, domain=5)
3. Sum signal scores into a composite confidence score (0–100)
4. Map confidence to verdict tier: ≥95 AUTO-APPROVE, 75–94 HUMAN-REVIEW, 50–74 LOW-CONFIDENCE, <50 INSUFFICIENT
5. AUTO-APPROVE verdicts must have `human_decision` set to `"auto"` and `decided_at` set to a valid ISO 8601 timestamp
6. Rate-limit HTTP requests to 1 request/second per domain during redirect and content checks

### Signal Modules
1. **Redirect signal:** Follow HTTP redirects from dead URL with `allow_redirects=False`, check if final location matches candidate. Timeout: 10s. Connection errors → score 0.
2. **Title match signal:** Extract `<title>` from candidate page, compare against archived title using `SequenceMatcher.ratio()` with case-insensitive normalization.
3. **Content similarity signal:** Fetch candidate page, strip HTML tags to plain text, compare against archived content using `SequenceMatcher.ratio()`.
4. **URL path signal:** Compare URL path components between dead URL and candidate using `urllib.parse`.
5. **Domain match signal:** Compare domains of dead URL and candidate — exact match scores full weight.

### HITL Dashboard
1. Single-file HTTP server using `http.server.HTTPServer`, binding to `127.0.0.1` only
2. Serve inline HTML/CSS/JS with side-by-side iframe layout (Archive snapshot left, candidate right)
3. Header bar showing dead URL, candidate URL, confidence score, and investigation method
4. Action buttons: Approve, Reject, Abandon, Keep Looking
5. Keyboard shortcuts: `a` = approve, `r` = reject, `x` = abandon, `k` = keep looking
6. POST endpoint `/api/decide` receives `{dead_url, decision}`, validates input, updates verdict file on disk
7. Polling endpoint `/api/next` serves next review item (polled every 500ms when idle)
8. Iframe fallback: display text panel with archived metadata when iframe fails to load
9. Summary screen when all items are decided, showing counts per decision type

### CLI
1. `python -m slant score --report <path>` runs scoring engine
2. `python -m slant dashboard --verdicts <path> [--port PORT]` launches dashboard (default port 8913)
3. `--help` available for all subcommands

## Technical Approach
- **Scoring Engine (`slant/scorer.py`):** Pure Python module. Takes a forensic report dict, iterates candidates, computes each of the 5 signal scores using `requests` (redirect check), `difflib.SequenceMatcher` (title/content similarity), and `urllib.parse` (URL path comparison). Returns verdict dict.
- **Redirect Checker (`slant/signals/redirect.py`):** Follows HTTP redirects from dead URL with `allow_redirects=False`, checks if final location matches candidate. Timeout: 10s. Handles connection errors gracefully (score = 0 for this signal).
- **Content Comparator (`slant/signals/content.py`):** Fetches candidate page, extracts text content (strip HTML tags), compares against archived content from Cheery's report using `SequenceMatcher.ratio()`.
- **Title Matcher (`slant/signals/title.py`):** Extracts `<title>` from candidate page, compares against archived title using `SequenceMatcher.ratio()` with case-insensitive normalization.
- **URL Path Comparator (`slant/signals/url_path.py`):** Decomposes URLs via `urllib.parse`, compares path segments using `SequenceMatcher.ratio()`.
- **Domain Matcher (`slant/signals/domain.py`):** Exact domain comparison between dead URL and candidate URL.
- **Configuration (`slant/config.py`):** Configurable signal weights with defaults matching the design table. Allows tuning without code changes.
- **HITL Dashboard (`slant/dashboard.py`):** Single-file HTTP server using `http.server.HTTPServer`. Serves inline HTML/CSS/JS. POST endpoint `/api/decide` receives `{dead_url, decision}`, updates verdict file on disk. Polling endpoint `/api/next` serves the next review item.
- **CLI Entry Point (`slant/cli.py`):** `python -m slant score --report cheery-report.json` runs scoring. `python -m slant dashboard --verdicts verdicts.json` launches HITL server.

## Risk Checklist

- [x] **Architecture:** Yes — introduces new `slant/` module with scoring engine and HTTP server. Integrates downstream of Cheery's output. Architecture is additive, no existing modules modified.
- [x] **Cost:** Yes — makes HTTP requests to dead URLs (redirect check) and candidate URLs (content fetch). Rate-limited to 1 req/sec per domain. Also loads Internet Archive iframes in dashboard (no API cost, browser-side).
- [ ] **Legal/PII:** No PII handled. URLs are from the user's own blog content.
- [x] **Legal/External Data:** Yes — fetches from external URLs (dead links, candidates) and embeds Internet Archive snapshots. Wayback Machine permits iframe embedding. Respects `robots.txt` for content fetching via `requests` with appropriate User-Agent.
- [ ] **Safety:** Low risk — scoring is read-only analysis. Dashboard writes only to local verdict JSON file. No destructive operations until a separate "apply" step (out of scope).

## Security Considerations
- **Path Validation:** Verdict output path is constructed from issue ID; validated to ensure it stays within `docs/reports/`. No user-provided arbitrary paths. Symlinks are not followed — paths are resolved with `pathlib.Path.resolve()` and checked against the allowed directory.
- **Input Sanitization:** URLs from Cheery's report are validated (scheme must be `http` or `https`). Dashboard HTML escapes all URL strings before rendering to prevent XSS. POST body to `/api/decide` is validated against allowed decision values (`approved`, `rejected`, `abandoned`, `keep_looking`). Malformed JSON in POST body returns HTTP 400.
- **Permissions:** Dashboard binds to `localhost` only (127.0.0.1). No authentication needed for local-only server.
- **Iframe Security:** Dashboard iframes use `sandbox` attribute to restrict scripts in loaded content from accessing the parent frame.

## Files to Create/Modify
- `slant/__init__.py` — Package init
- `slant/__main__.py` — CLI entry point (`python -m slant`)
- `slant/cli.py` — Argument parsing for `score` and `dashboard` subcommands
- `slant/config.py` — Configurable signal weights with defaults
- `slant/scorer.py` — Main scoring engine: loads report, iterates candidates, computes verdicts
- `slant/models.py` — Verdict dataclass/TypedDict definitions
- `slant/signals/__init__.py` — Signals subpackage
- `slant/signals/redirect.py` — HTTP redirect detection signal
- `slant/signals/title.py` — Title fuzzy match signal
- `slant/signals/content.py` — Content similarity signal
- `slant/signals/url_path.py` — URL path similarity signal
- `slant/signals/domain.py` — Domain match signal
- `slant/dashboard.py` — HITL dashboard HTTP server with inline HTML/CSS/JS
- `tests/unit/test_scorer.py` — Unit tests for scoring engine with fixture data
- `tests/unit/test_signals.py` — Unit tests for individual signal modules
- `tests/unit/test_dashboard.py` — Unit tests for dashboard API endpoints
- `tests/fixtures/sample_forensic_report.json` — Test fixture: Cheery's forensic report
- `tests/fixtures/expected_verdicts.json` — Test fixture: expected verdict output
- `docs/reports/{IssueID}/implementation-report.md` — Implementation report
- `docs/reports/{IssueID}/test-report.md` — Test report

## Dependencies
- None (this is the first judge module; Cheery's report format is defined by interface contract in this issue)

## Out of Scope (Future)
- **Applying replacements to markdown files** — separate "executor" issue; Mr. Slant only judges
- **Batch processing UI** — dashboard shows one link at a time for MVP; batch table view deferred
- **Persistent database** — verdicts stored as JSON files for MVP; SQLite deferred
- **LLM-assisted content comparison** — content similarity uses `difflib` for MVP; LLM semantic comparison is a future enhancement
- **Multi-user dashboard** — localhost single-user only for MVP
- **Cheery integration** — "Keep Looking" sets the flag but doesn't auto-trigger Cheery re-investigation

## Open Questions
- None (all questions resolved)
- [x] Should confidence scoring use fixed weights or configurable? → Resolved: Configurable via `slant/config.py` with defaults matching the design table. Allows tuning without code changes.
- [x] Should the dashboard use WebSocket or polling? → Resolved: Simple polling (fetch `/api/next` every 500ms when idle). WebSocket adds complexity with no benefit for single-user local use.
- [x] What port for the dashboard? → Resolved: 8913 (default), configurable via `--port` flag.
- [x] How to handle iframes blocked by X-Frame-Options? → Resolved: Display fallback text panel with archived metadata when iframe fails to load. JavaScript `onerror` handler on iframe triggers fallback.

## Acceptance Criteria
- [ ] `python -m slant score --report sample_report.json` reads a forensic report and writes `verdicts.json` with one verdict object per dead link
- [ ] Each verdict contains all required fields: `dead_url`, `verdict`, `confidence` (integer 0–100), `replacement_url`, `scoring_breakdown` (object with 5 signal keys: `redirect`, `title_match`, `content_similarity`, `url_similarity`, `domain_match`), `human_decision`, `decided_at`
- [ ] A dead link with a 301 redirect to the candidate scores ≥40 on the `redirect` signal
- [ ] A candidate with identical title to the archived page scores ≥24 on the `title_match` signal (allowing for floating-point rounding of 25 × ratio)
- [ ] Verdict tier mapping is correct: score 95→AUTO-APPROVE, score 87→HUMAN-REVIEW, score 62→LOW-CONFIDENCE, score 31→INSUFFICIENT
- [ ] AUTO-APPROVE verdicts have `human_decision` set to `"auto"` and `decided_at` set to a valid ISO 8601 timestamp
- [ ] `python -m slant dashboard --verdicts verdicts.json` starts an HTTP server on `localhost:8913` and returns HTTP 200 for `GET /`
- [ ] Dashboard HTML contains two iframes: one with `web.archive.org/web/` prefix and one with the candidate URL
- [ ] Pressing keyboard key `a` on the dashboard sends a POST to `/api/decide` with `decision: "approved"` and the next link loads
- [ ] POST `/api/decide` with `decision: "approved"` updates the corresponding verdict in `verdicts.json` on disk with `human_decision: "approved"` and a valid `decided_at` timestamp
- [ ] POST `/api/decide` with an invalid decision value (e.g., `"maybe"`) returns HTTP 400
- [ ] When all review items are decided, dashboard displays a summary showing counts per decision type
- [ ] All unit tests pass: `poetry run pytest tests/unit/test_scorer.py tests/unit/test_signals.py tests/unit/test_dashboard.py`
- [ ] Scoring a report with zero candidates for a dead link produces verdict INSUFFICIENT with confidence 0

## Definition of Done

### Implementation
- [ ] Core scoring engine implemented with all 5 signal modules
- [ ] Configuration module with configurable weights implemented
- [ ] HITL dashboard implemented with side-by-side review interface
- [ ] CLI entry points for `score` and `dashboard` subcommands working
- [ ] Unit tests written and passing

### Tools
- [ ] `python -m slant` CLI documented with `--help` for all subcommands
- [ ] Document tool usage in module docstrings

### Documentation
- [ ] Update wiki pages affected by this change
- [ ] Update README.md if user-facing
- [ ] Update relevant ADRs or create new ones
- [ ] Add new files to `docs/0003-file-inventory.md`

### Reports (Pre-Merge Gate)
- [ ] `docs/reports/{IssueID}/implementation-report.md` created
- [ ] `docs/reports/{IssueID}/test-report.md` created

### Verification
- [ ] Run 0809 Security Audit - PASS (dashboard binds localhost, input sanitization, iframe sandboxing)
- [ ] Run 0817 Wiki Alignment Audit - PASS (if wiki updated)

## Testing Notes

**Scoring engine tests:** Use `tests/fixtures/sample_forensic_report.json` with pre-computed expected scores. Mock HTTP requests via `unittest.mock.patch` on `requests.get` to simulate redirects, page content, and timeouts. Do NOT mock the scoring math itself — test real weighted calculations against known inputs.

**Dashboard tests:** Use `unittest` with `http.client` to test API endpoints. Start server in a thread, send requests, verify responses and file mutations. Test keyboard shortcuts via Playwright or manual QA.

**Force error states:**
- Set redirect check timeout to 0.001s to trigger timeout handling
- Provide a forensic report with empty `candidates` array to test zero-candidate path
- Send malformed JSON to `/api/decide` to verify 400 response
- Provide a candidate URL with `X-Frame-Options: DENY` header (mock) to verify iframe fallback rendering

**Labels:** `feat`, `judge`, `link-resolution`, `hitl`

---

<sub>**Gemini Review:** APPROVED | **Model:** `gemini-3-pro-preview` | **Date:** 2026-02-16 | **Reviews:** 2</sub>
