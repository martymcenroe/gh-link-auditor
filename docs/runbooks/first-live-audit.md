# First Live Audit Runbook

> **Completed one-time procedure (2026-07-28).** This was the "we have never run a real
> campaign" walkthrough. That moment has passed: 4 PRs submitted, 3 merged. It also predates
> preflight and the current toolchain. For what to run now, start at
> [`0000-start-here.md`](0000-start-here.md).

This is the one-time "we've never actually run a real campaign" runbook. Use it when you sit down tomorrow morning. The general operator reference is [`operator-guide.md`](operator-guide.md); this one is specifically for the first end-to-end run that submits a real PR to a real upstream repo.

**Reminder of the operating model:** Claude runs the pipeline. You watch, decide, and review. The HITL prompts at N4 are the only place you type into a console.

---

## 1. Kickoff (one sentence)

When you sit down, paste this to Claude:

> "Run the first-live-audit runbook from `docs/runbooks/first-live-audit.md`."

That's the trigger. Everything below describes what Claude will do and what you need to be watching for. Don't try to memorize it — just keep this file open and follow along.

---

## 2. Pre-flight (Claude does these; you confirm)

Before any audit runs, Claude will verify:

| Check | What it looks like | If it fails |
|---|---|---|
| `GITHUB_TOKEN` is set in env or `.env` | non-empty string, repo scope | You'll need to create a fine-grained PAT with `Contents: read`, `Pull requests: write`, `Issues: read` on the target repo, plus your fork. |
| `gh auth status` shows you logged in | "Logged in to github.com account martymcenroe" | Run `gh auth login` in your terminal. Claude can't do this — it's interactive. |
| `~/.ghla/ghla.db` is reachable | file exists (created on first run) or parent dir writable | Nothing — Claude creates it. |
| Test suite is green on main | `1796 tests collected ... passed` | If it isn't, stop. Something rotted overnight. |

**Your job in pre-flight:** if `gh auth login` is needed, Claude will tell you. That's the only manual step here.

---

## 3. Pick a first target

Claude will propose a target. **You decide if it's a good first run.**

A good first target has:

- **A real maintainer who responds to PRs** (check recent PR history — 1+ merged from outside contributors in the last 6 months).
- **Documentation with actual dead links** (otherwise the pipeline finishes with "0 fixes" and you've learned nothing).
- **Small enough docs corpus** to fit under `--max-links 50` (default circuit breaker). Big monorepos blow past 50 instantly.
- **Permissive contribution policy** — no maintainers known for being hostile to outside link fixes.

Good first-run candidates (suggestions, you pick):

1. **A repo you maintain or have contributed to before.** You know the maintainer culture; no surprises.
2. **A `pallets/flask`-class python doc repo** (e.g., the `run.py` test harness already points at `pallets/flask`). Mature, well-staffed, no hostility risk.
3. **A small CLI tool repo** where the docs are a single README.md. Easy to reason about.

**Anti-patterns for a first run:**

- Anything from `awesome-*` lists (huge link counts; trips circuit breaker).
- Repos with no merged PRs in 12+ months (maintainer is gone; PR will rot).
- Anything from your own employer if there's any policy ambiguity.

Tell Claude your pick or say "use `pallets/flask` as the first run."

---

## 4. Phase 1 — Dry run (no PR yet)

Claude runs the pipeline with `--dry-run`. Stages N0 → N1 → N2 → N3 → stop.

**What you'll see at the end:**

```
ghla: scanning https://github.com/<owner>/<repo> (dry-run)
      max-links=50  max-cost=$5.00  confidence=0.8

[N0 Load Target] ...
[N1 Scan]        ...
[N2 Investigate] ...
[N3 Judge]       ...

Summary: Found N dead links, generated 0 fixes.
```

**Your decision points:**

| Output | Decision |
|---|---|
| `Found 0 dead links` | The repo is healthy. Pick a different target. |
| `Found 1-5 dead links, all garbage from example docs` | Pipeline working, but no real signal. Pick a different target. |
| `Found N real dead links, plausible replacements proposed` | Proceed to Phase 2. |
| `Circuit breaker tripped at 50 dead links` | Either raise `--max-links` or narrow the target (subdirectory scan). |

Claude will summarize the candidates table — look at the proposed replacements and judge if they're plausible (same content at a new URL? archive.org snapshot? wikipedia disambiguation?).

---

## 5. Phase 2 — Full run with HITL (still no PR yet)

**Important context switch:** the dry-run in Phase 1 ran in Claude's Bash tool. The full run cannot, because N4 needs interactive stdin and Claude's tool has no terminal — `input()` would block forever.

So Phase 2 runs in **your own console**. Claude will hand you the exact command, you paste it into your terminal, you handle the HITL prompts. After all verdicts are decided, the pipeline continues automatically through N5, the PR Preview gate, and N6.

The command will look like:

```
poetry run python -m gh_link_auditor.cli.main run <target> --verbose
```

(No `--dry-run` this time. Optionally `--max-links N` if Phase 1 found many.)

### N4 gate — every verdict below 0.8 confidence pauses here

The prompt shape:

```
Dead URL:    https://example.com/old-page
Source:      docs/README.md:42
Confidence:  65%
Proposed:    https://example.com/new-page
Found via:   archive
Reasoning:   Slant score: 65/100

[a]pprove / [r]eject / [s]kip / snoo[z]e / e[x]it:
```

**How to decide each one:**

1. **Click the dead URL** — does it 404? If it actually loads, mark `r` (reject — false positive).
2. **Click the proposed replacement** — does it serve the same content? If it's the same article at a new URL, `a`. If it's marketing fluff or unrelated, `r`.
3. **Trust the confidence as a tiebreaker.** Below 0.5 with no obvious match → `r`. Above 0.65 with a sensible-looking replacement → usually `a`.
4. **When in doubt, `r`.** A false-positive rejection costs nothing. A false-positive acceptance puts garbage in someone else's docs.

**All responses:**
- `a` — approve (the fix goes in the PR)
- `r` — reject (the dead link stays unfixed)
- `s` — skip (defer; the verdict stays unapproved, pipeline continues)
- `z` — snooze (push to the recheck queue, defaults to 7 days)
- `x` — exit (reject everything remaining and continue to N5)
- `Ctrl+C` — abort entirely

**`x` vs `Ctrl+C`:** `x` finishes the run with whatever you've approved so far (you may still get a PR). `Ctrl+C` aborts before N5/N6 (no PR).

### After N4, you'll see the PR preview gate

```
========== PR Preview ==========
Title: docs: fix N broken links
Body:
  Found N broken links via gh-link-auditor.
  Replacement candidates verified live...
Fixes: M
  1. docs/README.md
     https://example.com/old-page
     -> https://example.com/new-page
  ...
=================================
[r]eview / [s]ubmit / e[x]it:
```

**Decide:**
- `r` — show the preview again (useful if you scrolled past it).
- `s` — submit the PR.
- `x` — bail, no PR.

**`x` is your full undo.** Up to this point nothing has been pushed anywhere. After `s`, the next 30-60 seconds will create your fork (if not already forked), push a branch to it, and open the PR.

---

## 6. Phase 3 — PR submission (N5, N6)

Claude runs N5 (clone fork, apply fixes, commit, push) and N6 (open PR upstream). All automated; no decisions needed.

**What success looks like:**

```
N6: Fork ready: martymcenroe/<repo>
N6: PR created: https://github.com/<owner>/<repo>/pull/<N>
Trust: <owner>/<repo> → tier1_pending (first PR submitted)
```

The trust transition is the proof that the T11 work landed — first submit moves us to `tier1_pending`. On merge it will move to `tier1_proven`.

**What failure looks like:**

| Output | Cause | Recovery |
|---|---|---|
| `N6: fork failed: permission denied` | PAT lacks the right scope, or org disallows forks | Adjust PAT scopes, or pick a different target |
| `N6: git command failed: push ...` | Fork branch already exists from a previous attempt | Delete the branch on the fork, retry |
| `N6: trust update skipped: ...` | DB locked or corrupt; PR still won | Note for cleanup; doesn't block the PR |

A failure at N5/N6 after N4 approval is the worst case — you've already said yes but the PR didn't make it. Claude will surface the error and stop.

---

## 7. Phase 4 — Post-run verification

After the PR exists upstream, run these three checks (Claude does it):

### a. The PR itself

```
gh pr view <PR-URL>
```

Eyeball: does the diff look right? Did the fix-rendering match what the preview showed? If anything is off, **close the PR yourself before the maintainer sees it**:

```
gh pr close <PR-URL> --comment "Withdrawing - bug in auto-fix, will resubmit after fix"
```

### b. Local state

```
ghla metrics campaign
```

Expected output:

```
=== Campaign ===
  Scans: 1
  Dead links found: N
  Fixes generated: M
  PRs submitted: 1

=== Recent PRs ===
  https://github.com/<owner>/<repo>/pull/<N>  open  2026-05-13...
```

If counts show 0 here despite the PR existing, the DB write didn't land — file a bug. This is exactly the failure mode T10 (#176) was supposed to fix; verify it actually did.

### c. Trust state

```
ghla blacklist stats
```

Should show no entries yet (a fresh campaign has nothing blacklisted). If something shows up under `source=hostile`, that means the hostile detector fired during refresh — review the offending comment URL in `ghla blacklist list`. False positive? `ghla blacklist remove <id>`.

---

## 8. After the PR is open

This is the longest phase — days or weeks. Two things to watch:

### Daily refresh

Once a day, ask Claude:

> "Refresh PR statuses."

That runs `ghla metrics refresh`, which:

1. Polls every open PR for status changes (open → merged / open → closed).
2. On merge: trust transitions `tier1_pending` → `tier1_proven` (and after 14 more days, `tier1_proven` → `tier2_eligible`).
3. On close-without-merge with a maintainer fix nearby: auto-blacklist with `source="fix_stolen"`.
4. Scans comments for hostile-maintainer signals — auto-blacklist with `source="hostile"`.
5. After 30 days of no response: auto-blacklist with `source="unresponsive"` (90-day expiry).

You watch the output; you don't have to do anything unless an auto-blacklist looks wrong.

### Manual overrides

| Situation | Command |
|---|---|
| False-positive hostile blacklist | `ghla blacklist list` → find ID → `ghla blacklist remove <id>` |
| Want to re-allow an unresponsive repo early | Same |
| Want to permanently blacklist a repo manually | `ghla blacklist add <repo-url> --reason "..."` |

---

## 9. When to stop and ask Claude

| Situation | Why stop |
|---|---|
| Anything in pre-flight fails | Don't proceed with a broken setup |
| N1 finds zero or all-garbage dead links | The target isn't useful; pick another |
| Circuit breaker trips in dry-run | Decide: raise the limit or narrow the target |
| Any N4 verdict you can't decide in 30 seconds | Walk away, do it later. The pipeline waits. |
| N5 or N6 fails after N4 approval | Don't retry blind — diagnose first |
| `metrics campaign` shows zeros after a successful PR submission | T10's fix didn't work for your env; file a bug before continuing |

The general "if you're unsure, stop and ask" rule from `CLAUDE.md` applies to operator decisions too. The pipeline is fast to restart; bad outcomes are slow to undo.

---

## 10. Quick reference

| Command (Claude runs) | What it does |
|---|---|
| `poetry run python -m gh_link_auditor.cli.main run <target> --dry-run` | Phase 1 dry-run |
| `poetry run python -m gh_link_auditor.cli.main run <target>` | Phase 2 + 3 full run |
| `poetry run python -m gh_link_auditor.cli.main metrics campaign` | Post-run dashboard |
| `poetry run python -m gh_link_auditor.cli.main metrics refresh` | Daily PR status poll |
| `poetry run python -m gh_link_auditor.cli.main blacklist {list,stats,add,remove}` | Blacklist management |

These are listed for documentation, not because you'll type them. Claude does the typing. You watch and decide.
