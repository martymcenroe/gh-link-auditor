# Bulk Scan Kickoff Runbook

One-time kickoff procedure for the unattended 7,500-repo Python doc scan (#218). Designed for the operator to fire before going to bed; runs unsupervised for ~5 days; deliverable is a ranked markdown report when you return.

---

## Before you fire it

Quick checks (~2 min):

```bash
cd /c/Users/mcwiz/Projects/gh-link-auditor
git checkout main && git pull --ff-only         # latest #218
poetry install --quiet
echo "$GITHUB_TOKEN" | head -c 12                # confirm token resolves; output should NOT be empty
gh auth status                                   # confirm gh CLI logged in
poetry run python -m gh_link_auditor.cli.main bulk-scan --help
```

If any step fails, stop here and fix before firing.

## Fire it

Single command in your own terminal (NOT in Claude — Claude's bash backgrounds it differently and the run will outlive sessions):

```bash
cd /c/Users/mcwiz/Projects/gh-link-auditor
poetry run python -m gh_link_auditor.cli.main bulk-scan start --target 7500
```

Press Enter and walk away.

The runner prints the `run_id` it generated (format: `bulk-YYYYMMDDTHHMMSSZ`). **Note it** — you need it for status checks.

## What it does

1. **Selecting** (~30 min): GitHub Search by star-range slices → seeds ~7,500 Python repos into the DB.
2. **Inventorying** (~1 day): For each repo, one tree-list call + raw fetch of each doc file; extracts URLs.
3. **Checking** (~1 day): HEAD-probes every unique URL across the corpus (massive dedup; 20 parallel workers).
4. **Investigating** (~1 day): Runs N2 LinkDetective on each confirmed-dead URL; tier-1 candidates only.
5. **Scoring** (~1 hour): Picks top-3 per repo, filters to confidence ≥ 0.7, writes the ranked report.

Total wall time: ~3.5-4 days. Pad of ~1 day for retries / rate-limit backoffs / unexpected slowness.

## What gets written

| File | Updated | Purpose |
|---|---|---|
| `data/bulk-scan-heartbeat.txt` | every 5 min | Status snapshot you can `cat` from phone |
| `data/bulk-scan-sample.md` | after 100 findings | First 100 surfaced for spot-checking |
| `data/bulk-scan-report.md` | at end | **The deliverable — ranked list of all surface-able candidates** |
| `~/.ghla/ghla.db` | live | All state (resumable) |

## While you're away

### Check progress from your phone (optional)

If you have SSH or cloud-sync access:

```bash
cat data/bulk-scan-heartbeat.txt
```

Sample output:

```
run_id: bulk-20260514T010000Z
status: investigating
target_repo_count: 7500
repos_by_status: {'pending': 0, 'inventoried': 0, 'investigated': 4231, 'done': 0, 'error': 18}
total_findings: 1840
surfaced_findings: 0          # surfaces happen only in Stage 4
last_update: 2026-05-15T14:30:00Z
quality_sample: data/bulk-scan-sample.md
sample_median_confidence: 0.84
```

### What "good" looks like

After ~24h:
- `status` should be `inventorying` or `checking`
- `repos_by_status` shows progress out of 7500
- `total_findings` rising as Stage 3 kicks in

After ~48h:
- `status` should be `investigating`
- `sample_median_confidence` ≥ 0.7 (if it's lower, see "What 'bad' looks like" below)

### What "bad" looks like

| Symptom | Meaning | Action |
|---|---|---|
| `QUALITY_ABORTED: ...` | Median confidence dropped below 0.7 — bulk run killed itself | Wait for trip end; we'll diagnose then |
| `status: aborted` | Someone touched `data/bulk-scan-abort` | Likely intentional |
| `repos_by_status[error]` > 10% of target | Many per-repo failures | Wait for trip end; might be GH API issue |
| Heartbeat hasn't updated in > 1 hour | Process likely dead | SSH in; `ps aux | grep bulk-scan` |

### Stopping it gracefully

```bash
poetry run python -m gh_link_auditor.cli.main bulk-scan stop
```

Writes `data/bulk-scan-abort`. The runner notices at the next batch boundary (≤ ~100 repos) and exits cleanly with status `aborted`. State preserved — resume later with the same `run_id`.

### Resuming after a crash or reboot

```bash
poetry run python -m gh_link_auditor.cli.main bulk-scan start --run-id <run-id>
```

The runner reads the saved status and picks up at the appropriate stage. Repos with status `done` or `error` are skipped.

## When you're back

1. **Snapshot status:**

   ```bash
   poetry run python -m gh_link_auditor.cli.main bulk-scan status
   ```

   If `status: done`, proceed. If still running, decide whether to let it finish or `stop` + report partial.

2. **Read the report:**

   ```bash
   poetry run python -m gh_link_auditor.cli.main bulk-scan report --run-id <run-id>
   # writes data/bulk-scan-report.md
   ```

3. **Triage** — review the top-N entries in the markdown. Each line is:

   ```
   N. owner/repo  docs/foo.rst line 42: http://dead/ -> https://new/  (0.95, url_mutation)
   ```

   Triage rule of thumb at 30s/row:
   - URL pair makes sense + confidence ≥ 0.85 → file a one-link PR (use the existing flow per `feedback-one-link-pr-policy`)
   - URL pair makes sense + confidence 0.7-0.85 → manual verify (click both URLs); if real, file
   - URL pair looks wrong → reject; add to a "false-positive patterns" notes file for future tuning

## Known limitations

- **No PyPI tier-2 lookup (#215 deferred).** `numpy.scipy.org` → `numpy.org` class moves will be MISSED entirely. They're stored at confidence 0.0 (no candidate found) and won't appear in the surface report. Run #215 post-trip and re-investigate the misses.
- **No `sitemap_search` candidates.** Held out of tier-1 envelope. Some genuine moves get missed.
- **No content-similarity check on archive.org snapshots.** Archive.org candidates not emitted at all in tier-1 mode.
- **Star range 100-10000.** Mega-repos (>10000 stars) and tiny repos (<100 stars) excluded by design.

## Disaster recovery

- **Power outage:** state in DB survives. Resume with same `run_id`.
- **Disk full:** runner refuses new writes; the abort marker auto-trips; status becomes `aborted` cleanly.
- **GitHub PAT expired:** Stage 1 will start failing on every repo. Heartbeat will show all repos transitioning to `error`. Renew the PAT, resume with the same `run_id`.
- **Quality aborts on day 1:** Don't restart with same `run_id` — the abort flag persists. Start a fresh run after we diagnose post-trip.

## Quick reference

| Need | Command |
|---|---|
| Start | `poetry run python -m gh_link_auditor.cli.main bulk-scan start --target 7500` |
| Status | `poetry run python -m gh_link_auditor.cli.main bulk-scan status` |
| Stop gracefully | `poetry run python -m gh_link_auditor.cli.main bulk-scan stop` |
| Resume | `poetry run python -m gh_link_auditor.cli.main bulk-scan start --run-id <id>` |
| Generate report | `poetry run python -m gh_link_auditor.cli.main bulk-scan report --run-id <id>` |
| List all runs | `poetry run python -m gh_link_auditor.cli.main bulk-scan list-runs` |
