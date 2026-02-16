# The Clacks Network — LangGraph Pipeline & Campaign Dashboard

> "A man is not dead while his name is still spoken." — GNU Terry Pratchett. And a link is not dead while someone is willing to find where it went.

## User Story

As a **open-source contributor**,
I want **an automated pipeline that scans repos for dead links, investigates replacements, and submits fix PRs — with a campaign dashboard tracking my contributions**,
So that **I can systematically earn GitHub contribution credit by fixing broken documentation across the open-source ecosystem**.

## Objective

Wire the entire gh-link-auditor pipeline under LangGraph — from target repo ingestion through PR submission — and track campaign-wide contribution impact on a static HTML dashboard.

## UX Flow

### Scenario 1: Happy Path — Dry Run

1. User runs `ghla pipeline run --target org/repo --dry-run`
2. N0 loads target repo, enumerates `.md`/`.rst` files, checks `CONTRIBUTING.md` — no policy blocks found
3. N1 scans all files and finds 12 dead links
4. N2 investigates each dead link, finds replacement candidates for 10
5. N3 scores confidence on all 10 replacements — all score ≥ 0.85
6. N4 (HITL) is skipped (all high-confidence)
7. N5 generates a unified diff for the 10 fixes
8. Pipeline outputs the diff to stdout and exits with code 0
9. No GitHub API calls are made; no PR is created

### Scenario 2: Happy Path — Submit PR

1. User runs `ghla pipeline run --target org/repo --submit`
2. Pipeline executes N0–N5 as above
3. N6 forks the repo, creates branch `fix/dead-links-<timestamp>`, commits the diff, pushes, and opens a PR
4. N6 enforces rate limiting: maximum 5 PRs per run, minimum 60-second sleep between PR submissions
5. PR body includes: count of links fixed, list of affected files, attribution line, and uses the target repo's PR template if present
6. N7 writes the run to campaign DB (`campaign_runs`, `campaign_prs`, `campaign_repos`)
7. Pipeline outputs the PR URL and exits with code 0

### Scenario 3: Policy Block

1. User runs `ghla pipeline run --target org/restricted-repo --submit`
2. N0 loads target repo and parses `CONTRIBUTING.md`
3. `CONTRIBUTING.md` contains the keyword `no-bot` on line 14
4. Pipeline halts before N1 and logs `BLOCKED: policy violation — keyword 'no-bot' found at CONTRIBUTING.md:14`
5. N7 records the run as `blocked` in campaign DB
6. Pipeline exits with code 1

### Scenario 4: Low-Confidence Routing to HITL

1. User runs `ghla pipeline run --target org/repo --submit`
2. N3 returns 8 verdicts at confidence ≥ 0.85 and 2 verdicts at confidence 0.60 and 0.72
3. Pipeline routes the 2 low-confidence verdicts to N4 (terminal HITL review)
4. User reviews each verdict in the terminal and approves 1, rejects 1
5. N5 generates fixes for 8 auto-approved + 1 HITL-approved = 9 total
6. N6 submits PR with 9 fixes
7. N7 records run with `hitl_reviewed: 2, hitl_approved: 1, hitl_rejected: 1`

### Scenario 5: Resume After Interruption

1. User runs `ghla pipeline run --target org/repo --submit`
2. Pipeline completes N0, N1, N2, then is interrupted (Ctrl+C / crash) during N3
3. State is checkpointed via `SqliteSaver` — N0, N1, N2 outputs are persisted
4. User runs `ghla pipeline resume --run-id abc123`
5. Pipeline loads checkpointed state and resumes at N3
6. Pipeline completes N3–N7 normally

### Scenario 6: Dashboard Generation

1. User runs `ghla dashboard`
2. System reads campaign DB and generates `campaign-dashboard.html` using Jinja2 + Chart.js
3. Dashboard displays: total repos scanned, dead links found, PRs submitted, PRs merged, acceptance rate percentage
4. Per-repo table shows one row per scanned repo with columns: repo, dead links, fixed, PR number, status, contribution credit
5. All rendered data is HTML-escaped to prevent XSS from external source data (repo names, PR titles)
6. File is written to current directory; user opens it in a browser

### Scenario 7: Dashboard Refresh

1. User runs `ghla dashboard --refresh`
2. System queries GitHub API for current status of all tracked PRs (open → merged/closed)
3. Campaign DB is updated with fresh PR statuses
4. Dashboard HTML is regenerated with updated stats
5. If GitHub API rate limit is hit, system logs a warning and uses cached data for remaining PRs

### Scenario 8: Cost Circuit Breaker

1. User runs `ghla pipeline run --target org/large-repo --submit`
2. N1 finds 500 dead links
3. Pipeline checks `--max-links` parameter (default: 50) — 500 exceeds the limit
4. Pipeline logs `CIRCUIT BREAKER: 500 dead links found, exceeds max-links limit of 50. Processing first 50 only. Use --max-links to adjust.`
5. Pipeline processes only the first 50 dead links through N2–N7
6. N7 records `total_found: 500, processed: 50, skipped: 450` in campaign DB

### Scenario 9: Network Failure During PR Submission

1. User runs `ghla pipeline run --target org/repo --submit`
2. N0–N5 complete successfully, producing fixes for 10 links
3. N6 attempts to submit PR but GitHub API returns HTTP 503 (Service Unavailable)
4. N6 retries once after 5-second backoff; second attempt also fails
5. N7 records the run as `error` with `error_detail: "PR submission failed: HTTP 503 after 2 attempts"` in campaign DB
6. Pipeline exits with code 2 and logs `ERROR: PR submission failed. Run recorded. Use 'ghla pipeline resume --run-id <ID>' to retry.`
7. Checkpointed state preserves N5 output so resume will retry from N6

## Requirements

### Pipeline Orchestration
1. LangGraph `StateGraph` with `PipelineState` TypedDict flowing through 8 nodes (N0–N7)
2. Conditional edges: N0 → HALT on policy block; N3 → N4 for low-confidence (< 0.85); N3 → N5 for high-confidence (≥ 0.85)
3. Node-level checkpointing via LangGraph's built-in `SqliteSaver` for pipeline resumability
4. Each node receives and returns the full `PipelineState`

### Node Integration
1. N1 wraps existing `check_links.py` scanner (Lu-Tze)
2. N2 wraps Cheery forensic investigator module
3. N3 wraps Mr. Slant verdict engine
4. N0 (LoadTarget), N5 (GenerateFix), N6 (SubmitPR), N7 (Track) are new code

### PR Automation (N6)
1. Fork → branch → commit → push → PR workflow using `PyGithub` (primary) with `gh` CLI fallback
2. PR body includes: count of links fixed, list of affected files, attribution line `Fixed by [gh-link-auditor](repo-url)`
3. PR uses target repo's `.github/PULL_REQUEST_TEMPLATE.md` when present
4. Dry-run mode (`--dry-run`) is the default — `--submit` flag required for actual PR creation
5. **Rate limiting:** Maximum 5 PRs per run (configurable via `--max-prs-per-run`), minimum 60-second sleep between PR submissions to avoid GitHub anti-spam triggers

### Policy Engine
1. Regex + keyword parser for `CONTRIBUTING.md`
2. Detects `no-bot`, `no-pr`, and `contact-first` keywords
3. Results cached in `PipelineState.repo_policy` to avoid re-parsing
4. Pipeline halts before N1 when policy violation detected

### Cost Controls
1. **`--max-links` parameter** (default: 50): Limits the number of dead links processed through N2–N7 per run, acting as a circuit breaker against unbounded LLM/API costs
2. Pipeline logs a warning when dead links found exceed `--max-links` and records both `total_found` and `processed` counts in campaign DB
3. Estimated cost per dead link: 5–20 API calls (Cheery web searches + Mr. Slant LLM calls); default cap of 50 links bounds a single run to ~250–1000 API calls

### Campaign Database
1. SQLite tables: `campaign_runs`, `campaign_prs`, `campaign_repos` with foreign key relationships
2. Extends existing state DB schema from issue #5
3. Records run outcomes: completed, blocked, interrupted, error

### Dashboard
1. Static HTML generated via Jinja2 template + Chart.js for visualizations
2. All data rendered in dashboard HTML is explicitly HTML-escaped via Jinja2 autoescaping to prevent XSS from external source data (repo names, PR titles, link text)
3. Served locally or deployed to GitHub Pages
4. `--refresh` flag queries GitHub API for current PR statuses before regeneration

## Technical Approach

### Pipeline State Machine

```
[Target Repo]
    → [N0: LoadTarget] → Policy Check
        → PASS → [N1: Lu-Tze: Scan] → dead links
            → [N2: Cheery: Investigate] → candidates
                → [N3: Mr. Slant: Judge] → verdicts
                    → HIGH confidence → [N5: GenerateFix]
                    → LOW confidence → [N4: HITL Gate] → [N5: GenerateFix]
                        → [N6: Doc-Fix Bot: SubmitPR]
                            → [N7: Campaign DB: Track]
        → FAIL → [N7: Track as blocked]
```

- **LangGraph StateGraph:** `PipelineState` TypedDict flows through 8 nodes; conditional edges handle policy blocks (N0 → HALT) and confidence routing (N3 → N4 for low-confidence, N3 → N5 for high-confidence)
- **Node Integration:** N1 wraps existing `check_links.py` scanner; N2 wraps Cheery forensic investigator; N3 wraps Mr. Slant verdict engine; new code for N0, N5, N6, N7
- **PR Automation (N6):** Uses `PyGithub` (primary) or `gh` CLI (fallback) for fork → branch → commit → push → PR workflow; rate-limited to prevent anti-spam triggers
- **Cost Circuit Breaker:** `--max-links` parameter (default: 50) caps dead links processed per run; prevents unbounded API/LLM spend on large repos
- **Campaign DB:** SQLite tables (`campaign_runs`, `campaign_prs`, `campaign_repos`) extending existing state DB from issue #5
- **Dashboard:** Static HTML generated via Jinja2 template (autoescaping enabled) + Chart.js for visualizations; served locally or deployed to GitHub Pages
- **Policy Engine:** Regex + keyword parser for `CONTRIBUTING.md`; results cached in state to avoid re-parsing
- **Checkpointing:** LangGraph's built-in `SqliteSaver` for node-level state persistence and pipeline resumability

### State Definition

```python
class PipelineState(TypedDict):
    target_repo: str
    target_files: list[str]
    repo_policy: dict               # CONTRIBUTING.md parse results
    scan_results: list[dict]        # Per 00008 schema
    forensic_reports: list[dict]    # Cheery's output
    verdicts: list[dict]            # Mr. Slant's output
    human_decisions: list[dict]     # HITL results
    approved_fixes: list[dict]      # Ready to PR
    pr_url: str | None
    campaign_stats: dict
    error: str | None               # Pipeline-level error capture
    links_total_found: int          # Total dead links before circuit breaker
    links_processed: int            # Dead links actually processed (≤ max-links)
```

### Node Table

| Node | Character | Input | Output |
|------|-----------|-------|--------|
| N0: LoadTarget | — | Repo URL or local path | Repo metadata, file list, policy parse |
| N1: Scan | Lu-Tze | File list | Dead links report (JSON per 00008) |
| N2: Investigate | Cheery | Dead links | Forensic reports with candidates |
| N3: Judge | Mr. Slant | Forensic reports | Verdicts with confidence scores |
| N4: HumanReview | HITL Terminal | Low-confidence verdicts | Human decisions |
| N5: GenerateFix | — | Approved replacements | Git diff / patch |
| N6: SubmitPR | Doc-Fix Bot | Fix patch + repo | PR URL |
| N7: Track | Campaign DB | PR metadata | Updated campaign stats |

## Risk Checklist

- [x] **Architecture:** Yes — introduces LangGraph as orchestration layer; adds 8 pipeline nodes, campaign DB schema, and dashboard generation. This is the largest architectural addition to date.
- [x] **Cost:** Yes — each pipeline run invokes Cheery (web searches, Wayback API) and Mr. Slant (LLM calls for confidence scoring). Estimated 5–20 API calls per dead link. Circuit breaker via `--max-links` (default: 50) caps a single run. Rate limiting and caching required.
- [ ] **Legal/PII:** No PII handled. All data is public repository URLs and link metadata.
- [x] **Legal/External Data:** Yes — forks public repos, reads `CONTRIBUTING.md`, queries Wayback Machine, submits PRs. Policy engine (issue #4) ensures ToS/robots.txt compliance. Wayback Machine API has no restrictive ToS for read-only queries.
- [x] **Safety:** Yes — PR submission modifies external repos (via fork). Safeguards: policy check before any PR, dry-run mode by default, `--submit` flag required for actual PR creation, rate limiting (max 5 PRs/run, 60s between submissions) to prevent GitHub anti-spam bans.

## Security Considerations

- **Path Validation:** Target repo paths validated against directory traversal. Local paths must resolve within allowed directories. Symlinks resolved and checked before processing.
- **Input Sanitization:** Repo URLs validated against `github.com` domain pattern. PR body content escaped to prevent injection via malicious link text in target repos. Dashboard HTML output uses Jinja2 autoescaping to prevent XSS from external source data (repo names, PR titles, link text from scanned repositories).
- **Permissions:** Requires GitHub PAT with `repo` and `workflow` scopes. Token stored via environment variable `GITHUB_TOKEN`, never logged or committed. Token presence validated at pipeline start with clear error message if missing.
- **Fork Safety:** Pipeline only modifies the authenticated user's fork, never pushes to upstream repo directly.

## Files to Create/Modify

### New Files
- `src/gh_link_auditor/pipeline/graph.py` — LangGraph StateGraph definition, node wiring, conditional edges
- `src/gh_link_auditor/pipeline/state.py` — `PipelineState` TypedDict and state validation
- `src/gh_link_auditor/pipeline/nodes/load_target.py` — N0: repo loading, file enumeration, policy detection
- `src/gh_link_auditor/pipeline/nodes/scan.py` — N1: wrapper around existing `check_links.py`
- `src/gh_link_auditor/pipeline/nodes/investigate.py` — N2: wrapper around Cheery forensic engine
- `src/gh_link_auditor/pipeline/nodes/judge.py` — N3: wrapper around Mr. Slant verdict engine
- `src/gh_link_auditor/pipeline/nodes/human_review.py` — N4: terminal-based HITL review flow
- `src/gh_link_auditor/pipeline/nodes/generate_fix.py` — N5: diff/patch generation from approved replacements
- `src/gh_link_auditor/pipeline/nodes/submit_pr.py` — N6: fork → branch → commit → push → PR with rate limiting
- `src/gh_link_auditor/pipeline/nodes/track.py` — N7: campaign DB writes
- `src/gh_link_auditor/pipeline/policy.py` — CONTRIBUTING.md parser and policy engine
- `src/gh_link_auditor/campaign/db.py` — Campaign SQLite schema and queries
- `src/gh_link_auditor/campaign/dashboard.py` — HTML dashboard generator (Jinja2 + Chart.js)
- `src/gh_link_auditor/campaign/templates/dashboard.html` — Jinja2 template for campaign dashboard (autoescaping enabled)
- `tests/unit/test_pipeline_graph.py` — StateGraph wiring and conditional edge tests
- `tests/unit/test_pipeline_nodes.py` — Per-node unit tests with fixture data
- `tests/unit/test_policy_engine.py` — Policy detection and keyword parsing tests
- `tests/unit/test_campaign_db.py` — Campaign DB schema and query tests
- `tests/unit/test_rate_limiting.py` — PR submission rate limiting and circuit breaker tests
- `tests/unit/test_dashboard_xss.py` — Dashboard XSS prevention tests with malicious input fixtures

### Modified Files
- `src/gh_link_auditor/cli.py` — Add `pipeline run`, `pipeline resume`, `dashboard` subcommands; add `--max-links`, `--max-prs-per-run` parameters
- `pyproject.toml` — Add `langgraph`, `pygithub`, `jinja2` dependencies
- `docs/0003-file-inventory.md` — Register all new files

## Dependencies

- Issue #5 must be completed first (State Database — campaign DB extends this schema)
- Issue #4 must be completed first (Policy Engine — policy compliance check at N0)
- Issue #8 must be completed first (Dead Links Report Schema — N1 output format)
- Cheery (investigator) and Mr. Slant (judge) modules must exist (N2/N3 wrap these)

## Out of Scope (Future)

- **Web-based HITL dashboard** — Phase 1 uses terminal review; web HITL deferred to Phase 3
- **GitHub Actions cron scheduling** — deferred to Phase 4 (Scale)
- **Repo Scout integration** — deferred to Phase 4 (issue #3 dependency)
- **Target list management (100+ repos)** — deferred to Phase 4
- **PostgreSQL migration** — SQLite sufficient for MVP; scale decision deferred
- **Multi-language file support** — MVP scans `.md` and `.rst` only
- **Parallel node execution** — LangGraph supports it, but sequential is fine for MVP

## Open Questions

- None (all questions resolved)
<!-- Resolved questions:
- [x] LangGraph vs plain orchestrator? → Resolved: LangGraph for checkpointing, state management, and conditional routing
- [x] PyGithub vs `gh` CLI for PR submission? → Resolved: Support both; PyGithub primary, `gh` CLI fallback
- [x] Dashboard: Flask vs static HTML? → Resolved: Static HTML + Chart.js for MVP (zero server dependency)
- [x] Where to store campaign DB? → Resolved: Extend existing state DB from issue #5
- [x] Auto-approve threshold? → Resolved: confidence >= 0.85 auto-approves; below routes to HITL
- [x] Dry-run default? → Resolved: Yes, `--dry-run` is default; `--submit` flag required for actual PR creation
- [x] Cost circuit breaker? → Resolved: `--max-links` (default 50) caps dead links processed per run
- [x] PR rate limiting? → Resolved: Max 5 PRs/run, 60s sleep between submissions
-->

## Acceptance Criteria

- [ ] `ghla pipeline run --target org/repo --dry-run` executes N0→N1→N2→N3→N5 and outputs a diff to stdout without submitting a PR
- [ ] `ghla pipeline run --target org/repo --submit` executes full N0→N7 pipeline and returns a valid PR URL
- [ ] When `CONTRIBUTING.md` contains the keyword `no-bot`, pipeline halts before N1 and logs `BLOCKED: policy violation — keyword 'no-bot' found at CONTRIBUTING.md:<line_number>`
- [ ] When all verdicts have confidence ≥ 0.85, pipeline skips N4 (HITL) and proceeds directly to N5
- [ ] When any verdict has confidence < 0.85, pipeline routes to N4 and presents the verdict in the terminal for human review
- [ ] `PipelineState` is checkpointed after each node; `ghla pipeline resume --run-id <ID>` resumes from the last completed node
- [ ] Campaign DB contains tables `campaign_runs`, `campaign_prs`, `campaign_repos` with foreign key relationships
- [ ] `ghla dashboard` generates `campaign-dashboard.html` that displays: total repos scanned, dead links found, PRs submitted, PRs merged, and acceptance rate percentage
- [ ] `ghla dashboard --refresh` updates PR statuses from GitHub API and regenerates the dashboard
- [ ] Dashboard per-repo table shows one row per scanned repo with columns: repo, dead links, fixed, PR number, status, contribution credit
- [ ] PR body includes: count of links fixed, list of affected files, and attribution line `Fixed by [gh-link-auditor](repo-url)`
- [ ] PR uses target repo's PR template from `.github/PULL_REQUEST_TEMPLATE.md` when present
- [ ] All 8 pipeline nodes have unit tests with fixture input/output data
- [ ] Policy engine detects `no-bot`, `no-pr`, and `contact-first` keywords in `CONTRIBUTING.md` test fixtures
- [ ] N6 enforces rate limiting: maximum PRs per run defaults to 5 (configurable via `--max-prs-per-run`), minimum 60-second sleep between PR submissions
- [ ] `--max-links` parameter (default: 50) caps the number of dead links processed; when N1 finds more than `--max-links` dead links, pipeline processes only the first `--max-links` and logs `CIRCUIT BREAKER: <total> dead links found, exceeds max-links limit of <max>. Processing first <max> only.`
- [ ] Dashboard HTML output passes XSS validation: injecting `<script>alert(1)</script>` as a repo name in campaign DB produces escaped output `&lt;script&gt;` in generated HTML
- [ ] When N6 fails due to network error, N7 records the run as `error` with `error_detail` containing the failure reason, and pipeline exits with code 2

## Definition of Done

### Implementation
- [ ] Core feature implemented (all 8 pipeline nodes, campaign DB, dashboard generator, rate limiting, cost circuit breaker)
- [ ] Unit tests written and passing

### Tools
- [ ] CLI subcommands added: `pipeline run`, `pipeline resume`, `dashboard`
- [ ] CLI parameters added: `--max-links`, `--max-prs-per-run`
- [ ] Document tool usage in `--help` output

### Documentation
- [ ] Update wiki pages affected by this change
- [ ] Update README.md with pipeline and dashboard usage
- [ ] Create ADR for LangGraph adoption decision
- [ ] Add new files to `docs/0003-file-inventory.md`

### Reports (Pre-Merge Gate)
- [ ] `docs/reports/{IssueID}/implementation-report.md` created
- [ ] `docs/reports/{IssueID}/test-report.md` created

### Verification
- [ ] Run 0809 Security Audit — PASS (GitHub token handling, fork safety, input sanitization, XSS prevention)
- [ ] Run 0810 Privacy Audit — PASS (no PII, but verify no token leakage in logs)
- [ ] Run 0817 Wiki Alignment Audit — PASS (if wiki updated)

## Testing Notes

- **Policy block:** Create a test fixture `CONTRIBUTING.md` containing `no-bot` to verify N0 halts the pipeline
- **HITL routing:** Set confidence threshold fixtures: one set at 0.90 (auto-approve), one at 0.60 (routes to HITL)
- **Dry-run vs submit:** Verify `--dry-run` never calls GitHub API fork/PR endpoints (mock and assert zero calls)
- **Dashboard generation:** Use fixture campaign DB with known data; assert HTML output contains expected stat values
- **Dashboard XSS:** Insert repo names containing `<script>`, `<img onerror=...>`, and `javascript:` URIs into fixture campaign DB; assert all are escaped in generated HTML
- **Resumability:** Run pipeline, kill after N2, verify `resume` picks up at N3 with correct state
- **PR template:** Create fixture repo with `.github/PULL_REQUEST_TEMPLATE.md`; verify PR body incorporates template
- **Rate limiting:** Mock GitHub API and submit 7 PRs; verify only 5 are submitted and 60s sleep is called between each
- **Cost circuit breaker:** Create fixture with 100 dead links; run with `--max-links 10`; verify only 10 are processed through N2–N7
- **Network failure during N6:** Mock GitHub API to return HTTP 503; verify N7 records `error` status with `error_detail` and pipeline exits with code 2; verify `resume` retries from N6

## Implementation Phases

| Phase | Scope | Issues |
|-------|-------|--------|
| **Phase 1: Pipeline Core** | LangGraph state machine, N0–N3 integration, terminal HITL, basic N5, cost circuit breaker | This issue (core) |
| **Phase 2: PR Automation** | N6 fork/PR workflow, policy engine integration, PR template generation, rate limiting | Depends on #4 |
| **Phase 3: Dashboards** | Campaign dashboard, HITL web dashboard, Chart.js visualizations, XSS hardening | Depends on #5 |
| **Phase 4: Scale** | Target list management, Repo Scout (#3), GitHub Actions scheduling | Future |

---

**Labels:** `epic`, `size:xl`, `langgraph`, `pipeline`, `dashboard`, `contribution-tracking`