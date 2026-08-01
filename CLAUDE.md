# CLAUDE.md - gh-link-auditor Project

You are a team member on the gh-link-auditor project, not a tool.

## FIRST: Read AssemblyZero Core Rules

`C:\Users\mcwiz\Projects\AssemblyZero\CLAUDE.md` covers workflow scripts and merge cleanup.

Universal core rules (safety, paths, banned commands, Two-Strike, blocked-or-uncertain protocol) live in `C:\Users\mcwiz\Projects\CLAUDE.md` — auto-loaded for every project.

**This file adds gh-link-auditor-specific rules ON TOP of those.**

---

## Project Identifiers

- **Repository:** `martymcenroe/gh-link-auditor`
- **Project Root (Windows):** `C:\Users\mcwiz\Projects\gh-link-auditor`
- **Project Root (Unix):** `/c/Users/mcwiz/Projects/gh-link-auditor`
- **Worktree Pattern:** `gh-link-auditor-{IssueID}` (e.g., `gh-link-auditor-45`)

---

## Project-Specific Workflow Rules

### Required Workflow

- **Docs before Code:** Write the LLD (`docs/lld/active/`) before writing code
- **Worktree before code:** `git worktree add ../gh-link-auditor-{ID} -b {ID}-short-desc`
- **Push immediately:** `git push -u origin HEAD`

### Reports (optional)

For non-trivial PRs, write `docs/reports/active/10{IssueID:04d}-implementation-report.md` and `docs/reports/active/10{IssueID:04d}-test-report.md`. Hotfixes, docs-only PRs, and bundled umbrella PRs (e.g. Phase B's 10-PR sweep under #281) skip per-PR reports.

No orchestrator review gate exists. Merge when CI passes and Cerberus-AZ approves — see universal `CLAUDE.md` → *Merging PRs (Universal)*.

---

## Documentation Structure

This project uses the **1xxxx numbering scheme** (project-specific implementations):

| Directory | Range | Contents |
|-----------|-------|----------|
| `docs/lld/` | 1xxxx | Low-level designs |
| `docs/reports/` | 1xxxx | Implementation & test reports |
| `docs/standards/` | 00xxx | Project-specific standards |
| `docs/adrs/` | 00xxx | Architecture Decision Records |

---

## Campaign Operations

Submission sessions follow `docs/runbooks/0001-shipping-the-approved-backlog.md` — refresh-first, 7-day pass-verdict freshness, throughput caps, pause triggers, open-PR aging. Read it before shipping any candidate.

---

## Cross-Session Context

The source of truth for prior sessions is `data/handoff-log.md` — append-only, managed by `/handoff` and consumed by `/onboard`.

`docs/session-logs/` is **gitignored, NOT retired.** `/handoff` still writes its session-log entry there every session — untracked and machine-local, so session narrative never leaks to GitHub (that is why it was removed from tracking in `253-remove-session-logs`).

**Gitignoring an artifact says where it may travel, never whether it gets produced.** An agent that reads "not tracked" as "stop writing it" has silently dropped a skill step. Skill instructions are explicit authorization: the only valid reason to skip one is the skill's own instructions saying so.

---

## GitHub CLI Safety

- ALWAYS use `--repo martymcenroe/gh-link-auditor` explicitly
- NEVER rely on default repo inference

---

## You Are Not Alone

Other agents may work on this project. Check `data/handoff-log.md` for recent context.
