# Runbook 0000 — Start Here

You have been away. This is the only page you need to re-enter the campaign. Everything here is a real command against the real machine.

---

## What this project does, in three sentences

It scans public GitHub repos for dead documentation links, finds the live replacement, and submits **one link fix per PR** to the maintainer. Each PR is a low-stakes way to earn a real contribution; a *merged* PR proves the maintainer is receptive, which is the actual prize — those repos become candidates for deeper contributor work. Quality beats volume: the corpus already produces far more candidates than anyone can review, so the whole system is tuned to hand you a short list you can trust.

## Scoreboard (as of 2026-07-28)

| | |
|---|---|
| Campaign PRs submitted | 4 |
| Merged | **3** — realpython/python-guide, OasisLMF/OasisLMF, AndreaVidali/Deep-QLearning-Agent-for-Traffic-Signal-Control |
| Rejected | 1 — pallets/flask (maintainer anti-AI policy; org is blacklisted) |
| Ready to submit right now | **4 candidates**, all preflighted today |

A 3-of-4 merge rate is the evidence that the approach works. The constraint is not finding candidates — it is deciding and submitting.

---

## The loop (this is the whole job)

### 1. Refresh what the world did while you were gone

```
poetry run python -m gh_link_auditor.cli.main metrics refresh
```

Polls GitHub for every open PR, records merges, promotes trust, and auto-blacklists hostile or unresponsive repos. **Always run this first.** It went unrun from 2026-05-26 to 2026-07-28 and three real merges sat undetected the whole time.

### 2. See where you stand

```
poetry run python -m gh_link_auditor.cli.main metrics campaign
poetry run python -m gh_link_auditor.cli.main curation list
```

`campaign` is the aggregate view — trust the **acceptance rate** and the **Recent PRs** list; the "Repos scanned" and "PRs submitted" counters currently read 0 from an unwritten table (known bug, #449).

`curation` lists repos that **merged** one of your PRs — the ones worth real contributor time. Mark decisions as you make them so the list shrinks:

```
poetry run python -m gh_link_auditor.cli.main curation set OasisLMF/OasisLMF --status evaluating --notes "why"
```

### 3. Pick a candidate and read it properly

These four passed preflight today. Higher score is a safer bet, not a better repo:

| Repo | Score |
|---|---|
| jftuga/less-Windows | 97 |
| nvidia-cosmos/cosmos-cookbook | 96 |
| Becksteinlab/GromacsWrapper | 93 |
| act-now-coalition/covid-data-model | 90 |

Before submitting, read the full analysis — repo metadata, the exact source line, the diff, all ten gates, the maintainer's recent-PR behaviour, the PR that would actually be filed, and a risk table:

```
poetry run python -m gh_link_auditor.cli.main candidate-analysis jftuga/less-Windows
```

Read **section 10 (risk)** and the **net risk** line. A passing score with `moderate` net risk usually means the maintainer is inactive or rarely merges outsiders — still worth filing, but expect silence. `hold` means don't.

Add `--no-live` to skip every GitHub call (renders from the database and the preflight report only) if you are offline or rate-limited. Note that you will be the **first person to run the live path** — it is covered by unit tests against a fake GitHub interface, but the agent is barred from exercising it for real because it reads through your `gh` credentials. If a live read fails it exits 3 and tells you to re-run with `--no-live`.

### 4. Submit (you run this, not the agent)

```
poetry run python tools/derive_replacement_prs.py --repo <owner/repo> --campaign-allowed --auto-approve --max-prs 1
```

A pinentry box will ask for your GPG passphrase — that decrypts the campaign PAT in-process. It prompts every time by design. Add `--dry-run` instead of `--auto-approve` to see the diff without filing anything.

**Caps:** 5 PRs/day campaign-wide, one open PR per maintainer, one link per PR. Details in [runbook 0001](0001-shipping-the-approved-backlog.md).

### 5. Afterwards

Confirm the new PR shows up in `metrics campaign`. If it doesn't, the feedback loop is broken and nothing downstream will work — that exact gap hid a merge for two months (#424).

---

## If the ready list runs dry

Re-preflight candidates you already have in the database:

```
poetry run python tools/derive_replacement_prs.py --repo <owner/repo> --preflight-report-only --campaign-allowed
```

**Any pass verdict older than 7 days must be re-run before you trust it.** Of five verdicts from 2026-05-25 re-checked on 2026-07-28, two had rotted — the *candidate* URLs had themselves died.

To generate new candidates from scratch, that is a bulk scan (multi-day, unattended): [`bulk-scan-kickoff.md`](bulk-scan-kickoff.md). Check for abandoned runs first:

```
poetry run python -m gh_link_auditor.cli.main bulk-scan reconcile        # dry-run
poetry run python -m gh_link_auditor.cli.main bulk-scan reconcile --apply
```

---

## Decisions currently waiting on you

| What | Where |
|---|---|
| Finish the DocFix-Bot storage consolidation, or amputate the dead `submissions` table — blocks the #395 orchestrator's design | #425 |
| Land the CI ruff pin: `poetry run python tools/pin_ruff_in_lint_workflow.py` | #428 |
| Purge test-pollution rows from the production DB | #438 |
| Mark the three abandoned bulk-scan runs aborted (`reconcile --apply`) | #426 |
| A `git stash` from 2026-07-28 holds superseded local edits — drop it or pop it | — |

---

## Stop and think if you see

- **A hostile or anti-AI comment on one of your PRs** — `metrics refresh` auto-blacklists, but read it yourself and consider whether the pattern applies more broadly.
- **A maintainer applying your fix without merging your PR** ("fix-stealing") — auto-detected and blacklisted, but it is a signal about that maintainer.
- **Two rejections in a row** — stop submitting and work out what changed.
- **Any command asking you to bypass a safety flag** (`--force`, `--admin`, `--no-verify`) — that is never the right answer here; investigate what is actually blocking.

## Where the other runbooks fit

- [`0001-shipping-the-approved-backlog.md`](0001-shipping-the-approved-backlog.md) — the cadence rules in full. Read before a submission session.
- [`bulk-scan-kickoff.md`](bulk-scan-kickoff.md) — generating new candidates at scale. Historical but still the reference for the scan itself.
- [`first-live-audit.md`](first-live-audit.md), [`operator-guide.md`](operator-guide.md) — written 2026-05-22 for the single-repo pipeline with interactive HITL prompts, **before** preflight, the campaign gate, and the current toolchain existed. Useful for understanding how the pipeline works internally; **do not follow them as procedure**.
