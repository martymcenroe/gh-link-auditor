# The Clacks Network — LangGraph Pipeline & Campaign Dashboard

> "A man is not dead while his name is still spoken." — GNU Terry Pratchett. And a link is not dead while someone is willing to find where it went.

## The Vision

Stitch the entire gh-link-auditor pipeline together under LangGraph, from scanning a target repo to submitting a PR with fixed links — and track it all on a campaign dashboard that shows contribution impact.

The ultimate goal: **earn GitHub contribution credit** by systematically finding and fixing broken documentation links across the open-source ecosystem.

## The Pipeline (LangGraph StateGraph)

```
[Target Repo]
    → [Lu-Tze: Scan] — Find all links, check which are dead
    → [Cheery: Investigate] — For each dead link, find replacement candidates
    → [Mr. Slant: Judge] — Score confidence on each replacement
    → [HITL Gate] — Human reviews low-confidence replacements
    → [Doc-Fix Bot: PR] — Fork, fix, commit, push, create PR
    → [Campaign DB: Track] — Record PR status, contribution credit
```

### Nodes

| Node | Character | Input | Output |
|------|-----------|-------|--------|
| N0: LoadTarget | — | Repo URL or local path | Repo metadata, file list |
| N1: Scan | Lu-Tze | File list | Dead links report (JSON per 00008) |
| N2: Investigate | Cheery | Dead links | Forensic reports with candidates |
| N3: Judge | Mr. Slant | Forensic reports | Verdicts with confidence scores |
| N4: HumanReview | HITL Dashboard | Low-confidence verdicts | Human decisions |
| N5: GenerateFix | — | Approved replacements | Git diff / patch |
| N6: SubmitPR | Doc-Fix Bot | Fix patch + repo | PR URL |
| N7: Track | Campaign DB | PR metadata | Updated campaign stats |

### State

```python
class PipelineState(TypedDict):
    target_repo: str
    target_files: list[str]
    scan_results: list[dict]        # Per 00008 schema
    forensic_reports: list[dict]    # Cheery's output
    verdicts: list[dict]            # Mr. Slant's output
    human_decisions: list[dict]     # HITL results
    approved_fixes: list[dict]      # Ready to PR
    pr_url: str | None
    campaign_stats: dict
```

### Policy Adherence

Before touching any repo:
1. Check for `CONTRIBUTING.md` — parse for bot/PR policies
2. Respect `no-bot`, `no-pr`, `contact-first` keywords (#4)
3. Follow the repo's commit convention (Conventional Commits, etc.)
4. Use the repo's preferred PR template if one exists

## Campaign Dashboard

A web dashboard (can be static HTML + JSON, or lightweight Flask) showing the **big picture** across all target repos:

### Dashboard Sections

#### 1. Campaign Overview
```
Total Repos Scanned:     47
Total Dead Links Found:  312
Replacements Found:      248 (79.5%)
PRs Submitted:           42
PRs Merged:              28 (66.7% acceptance rate)
Contributions Earned:    28 repos
```

#### 2. Per-Repo Table

| Repo | Dead Links | Fixed | PR | Status | Contribution |
|------|-----------|-------|-----|--------|-------------|
| org/project-a | 12 | 10 | #45 | Merged | Yes |
| org/project-b | 5 | 3 | #12 | Open | Pending |
| org/project-c | 8 | 8 | — | Blocked (policy) | — |

#### 3. Contribution Tracking

For each submitted PR, track:
- **PR Status:** Open / Merged / Closed
- **Who merged:** Author accepted directly, or maintainer merged our PR
- **Time to merge:** How long from PR submission to merge
- **Contribution credit:** Does this count toward our GitHub contribution graph?

#### 4. GitHub Score Impact

- Link to `github.com/martymcenroe` contribution graph
- Count of repos where we have merged contributions
- Before/after contribution count comparison

### Technical Approach

- Campaign data stored in SQLite (extends State Database #5)
- Dashboard: simple HTML + Chart.js, served locally or deployed to GitHub Pages
- Refreshed by running a `--dashboard` flag on the main CLI
- Data exported as JSON for external tooling

## Implementation Phases

### Phase 1: Pipeline Core
- Wire LangGraph state machine
- Integrate existing scanner (check_links.py → Lu-Tze)
- Integrate Cheery (detective) and Mr. Slant (judge)
- Basic HITL terminal flow (before dashboard)

### Phase 2: PR Automation
- Fork → branch → fix → commit → push → PR workflow
- Policy check module (#4)
- PR template generation

### Phase 3: Dashboards
- HITL review dashboard (Mr. Slant's courtroom)
- Campaign dashboard (stats + contribution tracking)

### Phase 4: Scale
- Target list management (100+ repos)
- Repo Scout integration (#3)
- Scheduling (GitHub Actions cron)

## Why This Matters

Every merged PR:
1. Fixes real documentation for real users
2. Earns a green square on the GitHub contribution graph
3. Establishes presence in the open-source community
4. Builds a portfolio of cross-repo contributions

This isn't just a link checker — it's a **contribution engine**.

Labels: epic, langgraph, pipeline, dashboard, contribution-tracking
