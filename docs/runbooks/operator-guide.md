# Operator Guide: Supervising gh-link-auditor

Claude runs the pipeline. You supervise. This guide tells you what to watch for, when you need to make a decision, and what can go wrong.

---

## Before a Run

Claude will handle installation, auth, and target selection. You just need to confirm:

- **Target repo**: Claude will propose a repo to audit. You approve or redirect.
- **Mode**: Dry-run (scan only, no changes) or full run (generates fixes). Always start with dry-run.
- **Limits**: Default is 50 dead links max, 0.8 confidence threshold. Claude will use sensible defaults unless you override.

---

## What Happens During a Dry-Run

Claude runs the pipeline. You watch. Here's what each stage does and what to look for.

### Stage 1: N0 Load Target (5-10 seconds)

**What it does:** Lists all doc files (.md, .rst, .txt, .adoc) in the target repo. For URL targets, uses GitHub API. For local paths, walks the filesystem.

**What to watch for:**
- If it says `errors:` immediately, the target URL is wrong or the repo doesn't exist
- If it reports 0 doc files, the repo has no documentation — nothing to audit

### Stage 2: N1 Scan (30 seconds - 3 minutes)

**What it does:** Reads every doc file, extracts URLs, HTTP HEADs each one to check if it's alive.

**What to watch for:**
- This is the slow part — one HTTP call per unique URL
- If there's no output for 2+ minutes, it's still working (N1 doesn't log progress)
- **Circuit breaker**: If dead links exceed `--max-links` (default 50), the pipeline stops here with exit code 2. Claude will tell you and ask if you want to raise the limit.

### Stage 3: N2 Investigate (1-5 minutes)

**What it does:** For each dead link, checks archive.org for snapshots, follows redirect chains, tries URL mutations.

**What to watch for:**
- You'll see `WARNING | archive_client | CDX API request failed for <url>` — this is NORMAL. Archive.org doesn't have everything.
- This is the slowest stage. Each dead link gets multiple HTTP calls with backoff.
- If you see the same warning repeating for obviously fake URLs (like `https://github.com/org/project` from example docs), those are placeholder URLs in LLD/design docs — not real dead links.

### Stage 4: N3 Judge (< 5 seconds)

**What it does:** Scores each replacement candidate using the Slant algorithm. Pure math, no HTTP calls. Fast.

**What to watch for:** Nothing — this is instant.

### Dry-run ends here

You'll see a one-line summary: `"Found X dead links, generated 0 fixes."` Exit code 0 means success. Exit code 2 means circuit breaker tripped.

**Your decision:** Review the dead link count. Are they real dead links or placeholder URLs from docs? If they look real, you may want to proceed to a full run.

---

## What Happens During a Full Run

Everything above, plus:

### Stage 5: N4 Human Review — YOU DECIDE HERE

**This is your gate.** For each verdict where the confidence score is below the threshold (default 0.8), the pipeline stops and asks you:

```
Dead URL: https://example.com/old-page
Source:   docs/README.md:42
Confidence: 65%
Proposed replacement: https://example.com/new-page
Found via: archive
Reasoning: Slant score: 65/100

[a]pprove / [r]eject / [s]kip / snoo[z]e / e[x]it:
```

**Important:** The HITL prompt runs in **your own console**, not Claude's Bash tool. Claude will hand you the command to run; you run it in your terminal. (Otherwise the prompt invisibly waits for input that never arrives.)

**What to decide for each verdict:**
- **Look at the dead URL.** Is this actually broken, or is it a false positive?
- **Look at the replacement.** Does it make sense? Is it the same content at a new location, or garbage?
- **Look at the confidence.** Below 0.5 is sketchy. 0.5-0.8 deserves scrutiny. Above 0.8 is auto-approved (you won't see it).

**Your responses:**
- `a` (or `approve` / `y` / `yes`) — accept the replacement
- `r` (or `reject` / `n` / `no`) — reject; the dead link stays as-is in the PR (it won't be "fixed" with garbage)
- `s` (or `skip`) — defer this one; pipeline continues to the next verdict, this one stays unapproved
- `z` (or `snooze`) — punt to the recheck queue (`ghla recheck` will pick it up later, default 7 days)
- `x` (or `exit`) — reject ALL remaining verdicts and continue to the next phase
- `Ctrl+C` — abort entirely

**High-confidence verdicts (>= 0.8) auto-approve silently.** You won't see them unless you lower the `--confidence` threshold.

### Stage 6: N5 Generate Fix (10-30 seconds)

**What it does:** For URL targets, shallow-clones the repo. Generates unified diffs for every approved replacement.

**What to watch for:**
- Clone failures (private repo, network issues)
- The summary: `"Found X dead links, generated Y fixes."`

### Stage 7: PR Preview Gate — YOU DECIDE HERE (URL targets only)

Between N5 and N6, the pipeline shows a preview of the PR it's about to open and asks you to confirm:

```
========== PR Preview ==========
Title: docs: fix N broken links
Body: ...
Fixes: M
  1. docs/README.md
     https://example.com/old-page
     -> https://example.com/new-page
  ...
=================================
[r]eview / [s]ubmit / e[x]it:
```

**Your responses:**
- `r` — re-display the preview (useful if scrolled past)
- `s` — submit the PR (proceeds to N6)
- `x` — abort, no PR opened

**This is your last undo.** After `s`, the next 30-60 seconds will fork the upstream (if needed), push to your fork, and open the PR.

If the repo is at trust level `new` or `tier1_pending` and any verdict used a tier-2 method (`sitemap_search`, `url_heuristic`, or any unverified candidate), those fixes are silently dropped from the preview — only the verified tier-1 fixes get submitted. The preview tells you how many were excluded.

### Stage 8: N6 Submit PR (30-60 seconds, URL targets only)

**What it does:** Forks the upstream (if not already), clones the fork, creates a branch, applies fixes, commits, pushes to the fork, opens the PR upstream. Then writes `tier1_pending` to the trust table for this repo (first-PR transition).

**What you'll see on success:**

```
N6: Fork ready: martymcenroe/<repo>
N6: PR created: https://github.com/<owner>/<repo>/pull/<N>
Trust: <owner>/<repo> → tier1_pending (first PR submitted)
```

**What to watch for if it fails:**

| Output | Cause | What to do |
|---|---|---|
| `N6: fork failed: permission denied` | PAT lacks scope, or org disallows forks | Adjust PAT, or pick a different target |
| `N6: git command failed: push ...` | Fork branch already exists | Delete the branch on the fork, retry |
| `N6: trust update skipped: <error>` | DB write failed; PR still landed | Log it, follow up — the PR exists |
| Error after `s` (PR Preview submit) | Network / auth issue | Diagnose before retrying — partial state may exist on the fork |

---

## After the Run (URL targets, PR opened)

The pipeline does not loop on its own. Once a PR is open upstream, you need to poll it periodically:

### Daily — refresh PR statuses

Ask Claude to run `ghla metrics refresh`. This polls every open PR and updates the local DB:

- **Merged →** trust transitions `tier1_pending` → `tier1_proven`. After 14 days at `tier1_proven`, the next refresh upgrades to `tier2_eligible` (riskier fixes become available for that repo).
- **Closed without merge + maintainer fixed it themselves →** auto-blacklist with `source="fix_stolen"`.
- **Hostile maintainer comment detected →** auto-blacklist with `source="hostile"`. Comment URL goes in the reason.
- **No response after 30 days →** auto-blacklist with `source="unresponsive"` (90-day expiry).

You watch the output. You only intervene if an auto-blacklist looks wrong.

### Anytime — dashboard

`ghla metrics campaign` prints aggregate counts and recent PRs:

```
=== Campaign ===
  Scans: N
  Dead links found: M
  Fixes generated: K
  PRs submitted: J

=== Recent PRs ===
  https://github.com/<owner>/<repo>/pull/<N>  open  <date>
  ...
```

If counts show 0 after a run that you saw succeed, the unified DB path resolution is broken for your env (#176 was supposed to fix this — verify the file `~/.ghla/ghla.db` actually got written).

### Manual override

| Situation | Command |
|---|---|
| Hostile-blacklist false positive | `ghla blacklist list` → find id → `ghla blacklist remove <id>` |
| Re-allow an unresponsive repo early | Same |
| Manually blacklist a repo | `ghla blacklist add <repo-url> --reason "..."` |
| Snoozed verdict comes due | `ghla recheck` re-verifies and either resolves or re-snoozes |

---

## Unattended Bulk Scan (the other workflow)

The pipeline above audits one repo at a time, with you supervising the HITL step. For thousand-repo unattended audits (no HITL), use **bulk-scan** — see `bulk-scan-kickoff.md` for the full kickoff procedure.

Quick orientation:

| Single-repo (`ghla run`) | Bulk-scan (`ghla bulk-scan`) |
|---|---|
| One repo per invocation | 7,500+ repos per invocation |
| Full N0-N6 pipeline (including PR submission) | Audit-only — produces a ranked candidate report, no PRs |
| HITL at N4 (you decide each verdict) | No HITL; auto-filters at confidence ≥ 0.7 |
| Wall time: minutes per repo | Wall time: days for 7,500 repos |
| Outputs: PRs upstream | Outputs: `data/bulk-scan-report.md` (ranked list you triage) |

Bulk-scan survives crashes (#230 persists Stage 2 per-URL to `url_check_cache`). Use `--run-id <existing>` to resume; pass `--new-run` if you want to start under a chosen id (#231 rejects unknown ids by default).

After triage, you can feed picked candidates back into the single-repo workflow if you want PRs opened upstream.

---

## Things That Can Go Wrong

| What you see | What it means | What to do |
|---|---|---|
| Pipeline crashes immediately | Import error, package not installed | Tell Claude to run `poetry install` |
| `errors:` after N0 | Bad target URL or repo doesn't exist | Check the URL, try again |
| 0 doc files found | Repo has no markdown/rst/txt/adoc files | Pick a different repo |
| Exit code 2 | Circuit breaker: too many dead links | Raise `--max-links` or pick a smaller repo |
| Archive.org warnings everywhere | Normal — archive.org doesn't have everything | Ignore unless ALL lookups fail |
| N4 prompt never appears in Claude's output | HITL is waiting on stdin; Claude's Bash tool has no terminal | Run the command in your own console (Claude will give you the exact invocation) |
| N4 shows garbage replacements | Slant scored badly but still proposed something | Reject with `r` |
| Clone fails in N5 | Private repo or auth issue | Check GITHUB_TOKEN has access |
| N5 succeeds but PR Preview shows fewer fixes than expected | Tier-2 fixes filtered out because the repo is at `new`/`tier1_pending` trust | This is correct behavior — repo earns tier-2 access after a first merge |
| N6: fork failed | PAT lacks `Pull requests: write` on the target, or org disallows forks | Adjust PAT or pick a different target |
| N6 fails after you said `s` at the preview | Partial state may exist on your fork | Don't retry blind — investigate fork branch first |
| `metrics campaign` shows 0 after a successful PR submission | DB write didn't land at the path the dashboard reads | Verify `~/.ghla/ghla.db` was written and `--db-path` defaults are aligned (#176 fix) |
| Hangs for 5+ minutes | N1 or N2 is grinding through many URLs | Wait, or Ctrl+C to abort |

---

## Pipeline Reference

| Node | Name | Duration | External calls | Human input |
|------|------|----------|----------------|-------------|
| N0 | Load Target | 5-10s | GitHub Contents API (URL targets) | None |
| N1 | Scan | 30s-3min | HTTP HEAD per URL | None |
| N2 | Investigate | 1-5min | archive.org, redirects, URL mutations | None |
| N3 | Judge | < 5s | None (Slant algorithm) | None |
| N4 | Human Review | Varies | None | **YES — approve/reject/skip/snooze/exit** |
| N5 | Generate Fix | 10-30s | Git clone of your fork (URL targets) | None |
| — | PR Preview Gate | Varies | None | **YES — review/submit/exit** (URL targets) |
| N6 | Submit PR | 30-60s | gh CLI (fork, push, create PR) | None |

**No LLM API keys needed.** The audit pipeline is HTTP-based and algorithmic. (`repo_scout`, the discovery tool, uses an LLM brainstormer; that's a separate flow.)

---

## CLI Reference (for Claude, not you)

`ghla` here means `poetry run python -m gh_link_auditor.cli.main`.

### `ghla run <target>`

| Flag | Default | What it does |
|------|---------|-------------|
| `--dry-run` | off | Stops after N3 — no human review, no fixes, no PR |
| `--max-links` | 50 | Circuit breaker: abort N1 if dead links exceed this |
| `--max-cost` | 5.00 | Cost limit in USD (not currently used — audit pipeline makes no LLM calls) |
| `--confidence` | 0.8 | Verdicts below this require N4 human review; above this auto-approve |
| `--verbose` | off | Detailed logging to stderr |
| `--db-path` | `~/.ghla/ghla.db` | Where state is read/written. Default unified across all subcommands as of #176. |

### Other subcommands

| Command | What it does |
|---|---|
| `ghla batch <yaml>` | Run the pipeline across many repos with rate limiting |
| `ghla metrics campaign` | Print aggregate counts + recent PRs |
| `ghla metrics refresh` | Poll GitHub for status changes on every open PR; trigger trust transitions and auto-blacklists |
| `ghla metrics scan-history` | List the last N scans with their outcomes |
| `ghla blacklist list` | Show active blacklist entries |
| `ghla blacklist add <repo-url> --reason ...` | Manual blacklist |
| `ghla blacklist remove <id>` | Manual unblacklist (use for false positives) |
| `ghla blacklist stats` | Counts grouped by source (manual, unresponsive, fix_stolen, hostile) |
| `ghla recheck` | Process snoozed verdicts that are due for re-verification |

### Exit codes

| Exit code | Meaning |
|-----------|---------|
| 0 | Success |
| 1 | Error |
| 2 | Circuit breaker triggered |
| 3 | Cost limit reached (audit pipeline doesn't trigger this today) |
