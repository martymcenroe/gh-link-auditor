# Pipeline Process

Two operating modes:

1. **Single-repo pipeline** (`ghla run`) — N0 through N6, includes HITL and PR submission
2. **Bulk-scan stages** (`ghla bulk-scan`) — Stage 0 through Stage 4, audit-only

Diagrams conform to `AssemblyZero/docs/standards/0004-mermaid-diagrams.md`.

## Single-repo pipeline (`ghla run <target>`)

```mermaid
flowchart TD
    Start(("ghla run<br/>URL or local path"))
    N0["N0: Load Target<br/>List doc files via<br/>GitHub Contents API"]
    N1["N1: Scan<br/>Extract URLs<br/>HEAD-probe each one"]
    Circuit{"Dead links<br/>≤ max-links?"}
    BadExit(("Exit 2:<br/>circuit breaker"))
    N2["N2: Investigate<br/>LinkDetective candidate gen<br/>(url_mutation, archive,<br/>wikipedia, github_resolver)"]
    N3["N3: Judge<br/>Slant algorithm<br/>score each candidate"]
    DryEnd(("Dry-run end:<br/>summary + exit 0"))
    DryRunGate{"--dry-run?"}
    N4{"N4: HITL Review<br/>per finding<br/>a/r/s/z/g/l/d/m/x"}
    Reject(("Verdict rejected<br/>(stays in DB)"))
    N5["N5: Generate Fix<br/>Clone fork<br/>Apply unified diff"]
    Preview{"PR Preview Gate<br/>r/s/x"}
    N6["N6: Submit PR<br/>Push to fork<br/>Open PR upstream<br/>trust → tier1_pending"]
    Done(("PR opened"))

    Start --> N0
    N0 --> N1
    N1 --> Circuit
    Circuit -->|"too many"| BadExit
    Circuit -->|"ok"| N2
    N2 --> N3
    N3 --> DryRunGate
    DryRunGate -->|"yes"| DryEnd
    DryRunGate -->|"no"| N4
    N4 -->|"a (approve, conf ≥ threshold auto)"| N5
    N4 -->|"r / x"| Reject
    N4 -->|"s / z (defer)"| Reject
    N5 --> Preview
    Preview -->|"s"| N6
    Preview -->|"x"| Reject
    N6 --> Done

    style Start fill:#60a5fa,stroke:#1e3a8a
    style DryEnd fill:#4ade80,stroke:#14532d
    style Done fill:#4ade80,stroke:#14532d
    style BadExit fill:#f87171,stroke:#7f1d1d
    style Reject fill:#f87171,stroke:#7f1d1d
    style N4 fill:#facc15,stroke:#713f12
    style Preview fill:#facc15,stroke:#713f12
```

**HITL keys at N4:**

| Key | Action |
|---|---|
| `a` / `y` | Approve replacement |
| `r` / `n` | Reject — keep dead URL as-is in PR |
| `s` | Skip — defer this verdict, continue |
| `z` | Snooze — punt to `recheck` queue (default 7d) |
| `g` | Open Google search for the dead URL in browser |
| `l` | Mark as live — false-positive flag for post-run analysis |
| `d` | Dead-product flag — punt to `rewrite_queue` for batch issue-filing |
| `m` | Manual URL entry — type a replacement directly |
| `u` | Show URL again (re-display verdict) |
| `x` | Exit — reject all remaining verdicts |

High-confidence verdicts (≥ 0.8 by default) auto-approve and don't show in HITL. Lower `--confidence` to gate more verdicts.

## Bulk-scan stages (`ghla bulk-scan start`)

```mermaid
flowchart TD
    Start(("bulk-scan start<br/>--target N"))
    Resume(("Resume<br/>--run-id <existing>"))

    S0["Stage 0: Selection<br/>~30 min<br/>gh search repos by star-range<br/>seed bulk_scan_repos"]
    S1["Stage 1: Inventory<br/>~1-2 hr<br/>per repo: tree-list + raw fetch<br/>extract URLs to bulk_scan_findings"]
    S2["Stage 2: Liveness<br/>~3-5 hr<br/>HEAD probe ThreadPool x20<br/>persist each to url_check_cache"]
    S3["Stage 3: Investigation<br/>~1-2 hr<br/>LinkDetective tier-1 on dead URLs<br/>quality stop-loss (median ≥ 0.7)"]
    S4["Stage 4: Scoring<br/>~minutes<br/>filter conf ≥ 0.7<br/>top-N per repo"]
    Report(("data/bulk-scan-report.md"))

    QuitGate{"abort marker?<br/>(data/bulk-scan-abort)"}
    Aborted(("status: aborted<br/>(state preserved)"))

    Start --> S0
    Resume -.->|"reads run<br/>status<br/>skips done stages"| S0
    S0 --> QuitGate
    QuitGate -->|"yes"| Aborted
    QuitGate -->|"no"| S1
    S1 --> S2
    S2 --> S3
    S3 --> S4
    S4 --> Report

    style Start fill:#60a5fa,stroke:#1e3a8a
    style Resume fill:#60a5fa,stroke:#1e3a8a
    style Report fill:#4ade80,stroke:#14532d
    style Aborted fill:#facc15,stroke:#713f12
    style QuitGate fill:#facc15,stroke:#713f12
    style S2 fill:#4ade80,stroke:#14532d
```

**Stage 2 persistence (#230):** The green-highlighted Stage 2 writes every probe result to `url_check_cache` as the future completes (30-day TTL). On resume, the runner reads cache and skips already-probed URLs. Power cuts and OOMs no longer lose this stage's work.

**Quality stop-loss (Stage 3):** First 100 surfaced candidates are sampled; median confidence < 0.7 → run auto-aborts with `status: quality_aborted`. Do not restart with same `run_id`; diagnose post-trip and start a fresh run.

**Resume semantics (#231):**

| Invocation | Behavior |
|---|---|
| `start` (no `--run-id`) | Auto-generates timestamped id, creates new run |
| `start --run-id <existing>` | Resumes — picks up at current stage |
| `start --run-id <unknown>` (no `--new-run`) | **Error 2** + "Did you mean..." suggestions |
| `start --run-id <unknown> --new-run` | Creates new run under chosen id |
| `start --run-id <existing> --new-run` | **Error 2** — drop `--new-run` to resume |

## Files written

| File | When | Purpose |
|---|---|---|
| `data/bulk-scan-heartbeat.txt` | Every ~5 min (Stages 1/3/4; Stage 2 gap tracked in #234) | Phone-readable status snapshot |
| `data/bulk-scan-sample.md` | After first 100 surfaced findings | Spot-check the quality before walking away |
| `data/bulk-scan-report.md` | At end of Stage 4 | The deliverable — ranked candidate list |
| `data/bulk-scan-abort` | When operator runs `bulk-scan stop` | Sentinel file — runner exits at next batch boundary |
| `~/.ghla/ghla.db` | Continuously | All state; resumable via `--run-id` |
