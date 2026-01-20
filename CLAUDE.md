# CLAUDE.md - gh-link-auditor

You are a team member on the gh-link-auditor project, not a tool.

## FIRST: Read AgentOS Core Rules

**Before doing any work, read the AgentOS core rules:**
`C:\Users\mcwiz\Projects\AgentOS\CLAUDE.md`

That file contains core rules that apply to ALL projects:
- Bash command rules (no &&, |, ;)
- Visible self-check protocol
- Worktree isolation rules
- Path format rules (Windows vs Unix)
- Decision-making protocol

---

## Project Identifiers

- **Repository:** `martymcenroe/gh-link-auditor`
- **Project Root (Windows):** `C:\Users\mcwiz\Projects\gh-link-auditor`
- **Project Root (Unix):** `/c/Users/mcwiz/Projects/gh-link-auditor`
- **Worktree Pattern:** `gh-link-auditor-{IssueID}`

---

## Project Overview

Enterprise-grade link auditor and repository graph expander with Human-in-the-Loop (HITL) resolution. Validates HTTP/HTTPS links in documentation using intelligent request handling.

**Tech Stack:** Python

---

## Key Files

| File | Purpose |
|------|---------|
| `check_links.py` | Main link validation script |
| `.github/` | GitHub Actions workflows |

---

## Development Workflow

### Run Link Audit

```bash
python /c/Users/mcwiz/Projects/gh-link-auditor/check_links.py
```

### GitHub CLI

Always use explicit repo flag:
```bash
gh issue create --repo martymcenroe/gh-link-auditor --title "..." --body "..."
```

---

## You Are Not Alone

Other agents may work on this project. Check `docs/session-logs/` for recent context.
