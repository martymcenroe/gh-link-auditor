- **LangGraph StateGraph:** `PipelineState` TypedDict flows through 8 nodes; conditional edges handle policy blocks (N0 → HALT) and confidence routing (N3 → N4 for low-confidence, N3 → N5 for high-confidence)
- **Node Integration:** N1 wraps existing `check_links.py` scanner; N2 wraps Cheery forensic investigator; N3 wraps Mr. Slant verdict engine; new code for N0, N5, N6, N7
- **PR Automation (N6):** Uses `PyGithub` or `gh` CLI for fork → branch → commit → push → PR workflow
- **Campaign DB:** SQLite tables (`campaign_runs`, `campaign_prs`, `campaign_repos`) extending existing state DB from issue #5
- **Dashboard:** Static HTML generated via Jinja2 template + Chart.js for visualizations; served locally or deployed to GitHub Pages
- **Policy Engine:** Regex + keyword parser for `CONTRIBUTING.md`; results cached in state to avoid re-parsing
- **Checkpointing:** LangGraph's built-in `SqliteSaver` for node-level state persistence and pipeline resumability

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
```

## Risk Checklist

- [x] **Architecture:** Yes — introduces LangGraph as orchestration layer; adds 8 pipeline nodes, campaign DB schema, and dashboard generation. This is the largest architectural addition to date.
- [x] **Cost:** Yes — each pipeline run invokes Cheery (web searches, Wayback API) and Mr. Slant (LLM calls for confidence scoring). Estimated 5–20 API calls per dead link. Rate limiting and caching required.
- [ ] **Legal/PII:** No PII handled. All data is public repository URLs and link metadata.
- [x] **Legal/External Data:** Yes — forks public repos, reads `CONTRIBUTING.md`, queries Wayback Machine, submits PRs. Policy engine (issue #4) ensures ToS/robots.txt compliance. Wayback Machine API has no restrictive ToS for read-only queries.
- [x] **Safety:** Yes — PR submission modifies external repos (via fork). Safeguards: policy check before any PR, dry-run mode by default, `--submit` flag required for actual PR creation.

## Security Considerations

- **Path Validation:** Target repo paths validated against directory traversal. Local paths must resolve within allowed directories. Symlinks resolved and checked.
- **Input Sanitization:** Repo URLs validated against `github.com` domain pattern. PR body content escaped to prevent injection via malicious link text in target repos.
- **Permissions:** Requires GitHub PAT with `repo` and `workflow` scopes. Token stored via environment variable `GITHUB_TOKEN`, never logged or committed.
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
- `src/gh_link_auditor/pipeline/nodes/submit_pr.py` — N6: fork → branch → commit → push → PR
- `src/gh_link_auditor/pipeline/nodes/track.py` — N7: campaign DB writes
- `src/gh_link_auditor/pipeline/policy.py` — CONTRIBUTING.md parser and policy engine
- `src/gh_link_auditor/campaign/db.py` — Campaign SQLite schema and queries
- `src/gh_link_auditor/campaign/dashboard.py` — HTML dashboard generator (Jinja2 + Chart.js)
- `src/gh_link_auditor/campaign/templates/dashboard.html` — Jinja2 template for campaign dashboard
- `tests/unit/test_pipeline_graph.py` — StateGraph wiring and conditional edge tests
- `tests/unit/test_pipeline_nodes.py` — Per-node unit tests with fixture data
- `tests/unit/test_policy_engine.py` — Policy detection and keyword parsing tests
- `tests/unit/test_campaign_db.py` — Campaign DB schema and query tests

### Modified Files
- `src/gh_link_auditor/cli.py` — Add `pipeline run`, `pipeline resume`, `dashboard` subcommands
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
-->

## Acceptance Criteria

- [ ] `ghla pipeline run --target org/repo --dry-run` executes N0→N1→N2→N3→N5 and outputs a diff to stdout without submitting a PR
- [ ] `ghla pipeline run --target org/repo --submit` executes full N0→N7 pipeline and returns a valid PR URL
- [ ] When `CONTRIBUTING.md` contains the keyword `no-bot`, pipeline halts before N6 and logs `BLOCKED: policy violation` with the specific keyword and line number
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

## Definition of Done

### Implementation
- [ ] Core feature implemented (all 8 pipeline nodes, campaign DB, dashboard generator)
- [ ] Unit tests written and passing

### Tools
- [ ] CLI subcommands added: `pipeline run`, `pipeline resume`, `dashboard`
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
- [ ] Run 0809 Security Audit — PASS (GitHub token handling, fork safety, input sanitization)
- [ ] Run 0810 Privacy Audit — PASS (no PII, but verify no token leakage in logs)
- [ ] Run 0817 Wiki Alignment Audit — PASS (if wiki updated)

## Testing Notes

- **Policy block:** Create a test fixture `CONTRIBUTING.md` containing `no-bot` to verify N0 halts the pipeline
- **HITL routing:** Set confidence threshold fixtures: one set at 0.90 (auto-approve), one at 0.60 (routes to HITL)
- **Dry-run vs submit:** Verify `--dry-run` never calls GitHub API fork/PR endpoints (mock and assert zero calls)
- **Dashboard generation:** Use fixture campaign DB with known data; assert HTML output contains expected stat values
- **Resumability:** Run pipeline, kill after N2, verify `resume` picks up at N3 with correct state
- **PR template:** Create fixture repo with `.github/PULL_REQUEST_TEMPLATE.md`; verify PR body incorporates template

## Implementation Phases

| Phase | Scope | Issues |
|-------|-------|--------|
| **Phase 1: Pipeline Core** | LangGraph state machine, N0–N3 integration, terminal HITL, basic N5 | This issue (core) |
| **Phase 2: PR Automation** | N6 fork/PR workflow, policy engine integration, PR template generation | Depends on #4 |
| **Phase 3: Dashboards** | Campaign dashboard, HITL web dashboard, Chart.js visualizations | Depends on #5 |
| **Phase 4: Scale** | Target list management, Repo Scout (#3), GitHub Actions scheduling | Future |

---

**Labels:** `epic`, `langgraph`, `pipeline`, `dashboard`, `contribution-tracking`