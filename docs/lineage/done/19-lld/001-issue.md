---
repo: martymcenroe/gh-link-auditor
issue: 19
url: https://github.com/martymcenroe/gh-link-auditor/issues/19
fetched: 2026-02-19T05:47:38.648812Z
---

# Issue #19: Phase 2+: Batch Execution Engine, PR Automation & Campaign Metrics

# Phase 2+: Batch Execution Engine, PR Automation & Campaign Metrics

> Retitled from "Architect and Build Automated Link Checking Pipeline" after gap analysis against #22 (The Clacks Network Phase 1).

## Context

Issue #22 covers the single-repo pipeline (N0–N5: scan, investigate, judge, review, fix). This issue captures everything **beyond** single-repo processing that was in the original vision but has no home elsewhere.

## Gap Analysis

The original #19 covered four phases. Here's where each concept landed:

| Original Concept | Now Covered By |
|------------------|---------------|
| Core link checker | #22 N1 (Lu-Tze), #1 (check_links.py) |
| Target repo list sourcing | #3 (Repo Scout) |
| Policy discovery (CONTRIBUTING.md) | #4 (Maintainer Policy Check) |
| Fork, clone, apply fixes, submit PR | #2 (Doc-Fix Bot) |
| Tracking database | #5 (State Database) — **done** |
| Single-repo pipeline orchestration | #22 (The Clacks Network Phase 1) |

**The following concepts are NOT captured by any existing issue:**

## 1. Batch Execution Engine (Iteration)

How do you run the #22 pipeline across **thousands** of repos?

- **Iteration loop** with configurable concurrency (sequential vs. parallel workers)
- **Rate limiting** — respect GitHub API limits across all repos, not just one
- **Resumability** — if the batch crashes at repo 347/2000, resume from 348
- **Error isolation** — one repo failure doesn't kill the batch
- **Progress tracking** — real-time display of batch progress (347/2000, 12 fixes found, 3 PRs submitted)
- **Backpressure** — slow down if GitHub rate limits are approaching, speed up when headroom exists
- **Target list integration** — consumes output from #3 (Repo Scout) as input

## 2. GitHub Authentication & Token Management

- **High-rate token configuration** — personal access token or GitHub App for elevated rate limits
- **Token rotation** — support multiple tokens for higher throughput
- **Rate limit awareness** — query `X-RateLimit-Remaining` headers and adapt batch speed
- **Auth validation** — verify token scopes before starting a batch run

## 3. Fork/Branch Maintenance & Cleanup

- **Post-PR cleanup** — delete local clones and branches after PR is submitted or merged
- **Stale fork pruning** — identify and optionally delete forks where PRs were rejected or repos archived
- **Storage management** — monitor disk usage of cloned repos, warn when approaching limits
- **Branch hygiene** — clean up remote branches after PRs are merged/closed

## 4. Campaign Metrics & Reporting

- **Acceptance rate** — percentage of submitted PRs that get merged
- **Time-to-merge** — how long from PR submission to merge
- **Rejection analysis** — categorize why PRs are rejected (wrong fix, style mismatch, not wanted)
- **Campaign dashboards** — visualize metrics over time
- **Per-run reports** — summary of a batch run (repos scanned, links found, fixes generated, PRs submitted)
- **ROI tracking** — effort spent vs. fixes merged

## Dependencies

- #22 (The Clacks Network Phase 1) — the single-repo pipeline this wraps
- #3 (Repo Scout) — provides the target repo list
- #2 (Doc-Fix Bot) — provides the PR submission mechanism
- #4 (Maintainer Policy Check) — policy-adherent commits
- #5 (State Database) — persistence layer (**done**)

## Relationship to Other Issues

```
#3 Repo Scout ──► target list ──► THIS (#19) batch engine ──► #22 pipeline (per repo)
                                       │                           │
                                       │                      #2 Doc-Fix Bot (PR submission)
                                       │                      #4 Policy Check (commit formatting)
                                       │
                                       └──► Campaign Metrics & Cleanup
```

## Out of Scope

- Single-repo pipeline orchestration (that's #22)
- Repo discovery algorithms (that's #3)
- PR generation mechanics (that's #2)
- CONTRIBUTING.md parsing (that's #4)
- Web-based dashboard UI (future issue if metrics warrant it)

## Original Issue

This was originally titled "feat: Architect and Build Automated Link Checking Pipeline". The LLD workflow failed 3x (Gemini BLOCKED on scope breadth). After the gap analysis, the scope was narrowed to only the concepts not captured by #22, #2, #3, or #4.