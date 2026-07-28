# Runbook 0001 — Shipping the Approved Backlog

One page. Read before each submission session. Spec: #336. Umbrella: #241.

## Before each batch (5 minutes)

1. **Refresh outcomes:** `poetry run python -m gh_link_auditor.cli.main metrics refresh`
   Updates merge/close statuses, fires trust promotion (`tier1_pending → tier2_eligible`), and applies auto-blacklists (hostile, anti-AI, fix-steal, 30-day unresponsive).
   *Why it's step 1:* this went unrun from 2026-05-26 to 2026-07-28 — three real merges sat undetected the entire time.
2. **Dashboard:** `poetry run python -m gh_link_auditor.cli.main metrics campaign`

(There is no installed `ghla` entry point; the module invocations above are the working forms.)

## Freshness rule

A `pass` verdict older than **7 days** must be re-preflighted before submission:

```
poetry run python tools/derive_replacement_prs.py --repo <owner/repo> --preflight-report-only --campaign-allowed
```

*Evidence:* of five 2026-05-25 pass verdicts re-run on 2026-07-28, two failed gate 6 — the **candidate** URLs themselves had died (404, 403). Verdicts rot from both ends.

## Throughput caps

- **Campaign-wide: max 5 PRs/day** (tunable; maintainer-ecosystem visibility limit).
- **Per maintainer:** one open PR per login at a time; ≥14 days between PRs to the same login. Manual rule until #334 enforces it in code.
- **One link per PR, always.** Deeper contributions happen only by maintainer invitation (merge/engagement → curation surface, #404).

## Spot-check ritual (from #314)

Operator reads the top candidate's full preflight report (gates + scores + URLs) before each batch. When #403's candidate-analysis tool lands, run it here instead.

## Submission (operator-run)

```
poetry run python tools/derive_replacement_prs.py --repo <owner/repo> --campaign-allowed --max-prs 1
```

Classic-PAT pinentry will prompt (ADR-0216). Use `--dry-run` first when in doubt.
**After each submit:** confirm the new row appears in the dashboard's recent-PRs list. A missing row breaks the feedback loop silently — python-guide#1186 went unrecorded for two months (#424).

## Pause triggers — stop the queue and investigate

- Any hostile / anti-AI blacklist addition in the latest refresh.
- GitHub secondary-rate-limit warnings from any tool.
- One of our PRs with `action_required` checks >24h.
- Two rejections in a row.

## Open-PR aging

| Age | Action |
|---|---|
| <30 days | Nothing. Normal. |
| 30 days | Refresh auto-blacklists the repo `unresponsive` (expiring) — future submissions pause; **leave the PR open**. |
| Beyond | Still leave it open. Never nudge, never self-close: python-guide#1186 merged on day 60. The open PR costs nothing; closure adds only visibility risk. |
