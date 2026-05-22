# 10235 Implementation Report

**Issue:** #235
**Branch:** `235-docs-refresh`

## Changes

| File | Change |
|---|---|
| `README.md` | Status table: hostile-detection moved Planned→Shipped; added anti-AI classifier (#200) and bulk-scan (#218). Subcommand table: added `ghla bulk-scan {start,status,stop,report,list-runs}`. Documentation section: added `docs/design/` and `docs/runbooks/` references. |
| `docs/runbooks/operator-guide.md` | Committed pending 9-day-old edits covering N4 HITL keys (a/r/s/z/x), PR Preview Gate (r/s/x), N6 Submit PR (#185), updated pipeline reference table, expanded CLI flag and exit-code tables. Added new "Unattended Bulk Scan" section linking out to bulk-scan-kickoff.md. |
| `docs/runbooks/bulk-scan-kickoff.md` | Resume section notes #230 persistence ("Stage 2 results survive crashes") and #231 unknown-id rejection (with `--new-run` instructions). Disaster recovery split per-stage; quality-aborts vs operator-aborts disambiguated. |
| `docs/runbooks/first-live-audit.md` | Committed (had been untracked since 2026-05-13). |
| `docs/lessons-learned.md` | Committed 4 pending lessons from bulk-scan work (#218, #220, #224, plus cleanup-skill venv-eviction). |
| `docs/design/architecture.md` | New: system architecture mermaid diagram + component descriptions. |
| `docs/design/pipeline-process.md` | New: single-repo pipeline (N0-N6) + bulk-scan (Stage 0-4) mermaid flowcharts, HITL key table, resume semantics table. |

## Diagrams

All three diagrams follow `AssemblyZero/docs/standards/0004-mermaid-diagrams.md`:

- `flowchart TD` (top-down)
- Quoted labels (`<br/>` for line breaks)
- No cycles in the process diagrams (Resume uses a separate start node with dashed entry to Stage 0)
- Bidirectional HITL flow uses TB + dashed return arrows per §7.2
- Dark-mode-safe styling — blue/green/yellow/purple at saturated mid-tones; no near-white or near-black fills

### Visual inspection (§8.5)

Each diagram was rendered via mermaid.ink to PNG and inspected with the Read tool. Findings in the test report.

## Out of scope

- New ADRs — none added; the existing architecture is documented, not re-decided.
- HITL key expansion in operator-guide beyond `a/r/s/z/x`. The pipeline-process.md table is the comprehensive reference (covers `g/l/d/m/u`); the operator-guide keeps the basic set so beginners aren't overwhelmed.
- GH wiki population — repo has it enabled but unused; `docs/` tree is the source of truth.
