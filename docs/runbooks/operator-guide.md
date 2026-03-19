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
Confidence: 0.65
Proposed replacement: https://example.com/new-page
Found via: archive
Reasoning: Slant score: 65/100

[y]es / [n]o:
```

**What to decide:**
- **Look at the dead URL.** Is this actually broken, or is it a false positive?
- **Look at the replacement.** Does it make sense? Is it the same content at a new location, or garbage?
- **Look at the confidence.** Below 0.5 is sketchy. 0.5-0.8 deserves scrutiny. Above 0.8 is auto-approved (you won't see it).
- **Type `y`** to approve the replacement, **`n`** to reject it
- **Ctrl+C** to abort and reject everything remaining

**High-confidence verdicts (>= 0.8) auto-approve silently.** You won't see them unless you lower the `--confidence` threshold.

### Stage 6: N5 Generate Fix (10-30 seconds)

**What it does:** For URL targets, shallow-clones the repo. Generates unified diffs for every approved replacement.

**What to watch for:**
- Clone failures (private repo, network issues)
- The summary at the end: `"Found X dead links, generated Y fixes."`

---

## Things That Can Go Wrong

| What you see | What it means | What to do |
|---|---|---|
| Pipeline crashes immediately | Import error, package not installed | Tell Claude to run `poetry install` |
| `errors:` after N0 | Bad target URL or repo doesn't exist | Check the URL, try again |
| 0 doc files found | Repo has no markdown/rst/txt/adoc files | Pick a different repo |
| Exit code 2 | Circuit breaker: too many dead links | Raise `--max-links` or pick a smaller repo |
| Archive.org warnings everywhere | Normal — archive.org doesn't have everything | Ignore unless ALL lookups fail |
| N4 shows garbage replacements | Slant scored badly but still proposed something | Reject with `n` |
| Clone fails in N5 | Private repo or auth issue | Check GITHUB_TOKEN has access |
| Hangs for 5+ minutes | N1 or N2 is grinding through many URLs | Wait, or Ctrl+C to abort |

---

## Pipeline Reference

| Node | Name | Duration | External calls | Human input |
|------|------|----------|----------------|-------------|
| N0 | Load Target | 5-10s | GitHub API (URL targets) | None |
| N1 | Scan | 30s-3min | HTTP HEAD per URL | None |
| N2 | Investigate | 1-5min | archive.org, redirects | None |
| N3 | Judge | < 5s | None (algorithmic) | None |
| N4 | Human Review | Varies | None | **YES — approve/reject** |
| N5 | Generate Fix | 10-30s | Git clone (URL targets) | None |

**No LLM API keys needed.** The entire pipeline is HTTP-based and algorithmic.

---

## CLI Reference (for Claude, not you)

| Flag | Default | What it does |
|------|---------|-------------|
| `--dry-run` | off | Stops after N3, no human review, no fixes |
| `--max-links` | 50 | Circuit breaker threshold |
| `--max-cost` | 5.00 | Cost limit (not currently used — no LLM calls) |
| `--confidence` | 0.8 | Below this = human review, above = auto-approve |
| `--verbose` | off | Detailed logging to stderr |

| Exit code | Meaning |
|-----------|---------|
| 0 | Success |
| 1 | Error |
| 2 | Circuit breaker triggered |
| 3 | Cost limit reached |
