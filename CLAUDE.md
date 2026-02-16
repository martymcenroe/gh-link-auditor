# CLAUDE.md - gh-link-auditor Project

You are a team member on the gh-link-auditor project, not a tool.

## FIRST: Read AssemblyZero Core Rules

**Before doing any work, read the AssemblyZero core rules:**
`C:\Users\mcwiz\Projects\AssemblyZero\CLAUDE.md`

That file contains core rules that apply to ALL projects:
- Bash command rules (no &&, |, ;)
- Visible self-check protocol
- Worktree isolation rules
- Path format rules (Windows vs Unix)
- Decision-making protocol

**This file adds gh-link-auditor-specific rules ON TOP of those core rules.**

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

### Reports Before Merge (PRE-MERGE GATE)

**Before ANY PR merge, you MUST:**

1. Create `docs/reports/active/1{IssueID}-implementation-report.md`
2. Create `docs/reports/active/1{IssueID}-test-report.md`
3. Wait for orchestrator review

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

## Session Logging

At end of session, append a summary to `docs/session-logs/YYYY-MM-DD.md`.

---

## GitHub CLI Safety

- ALWAYS use `--repo martymcenroe/gh-link-auditor` explicitly
- NEVER rely on default repo inference

---

## You Are Not Alone

Other agents may work on this project. Check `docs/session-logs/` for recent context.
