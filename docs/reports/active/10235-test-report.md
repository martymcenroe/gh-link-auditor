# 10235 Test Report

**Issue:** #235
**Branch:** `235-docs-refresh`

Docs-only change. No code modified → no unit tests. Verification is link integrity, content correctness, and mermaid render inspection.

## Mermaid auto-inspection (per AZ §8.5)

Procedure: base64-encode the diagram, fetch PNG from mermaid.ink, view via Read tool.

### `docs/design/architecture.md` — system architecture diagram

Rendered: `data/diagrams/architecture.png` (101 KB)

```
**Mermaid Auto-Inspection:**
- Touching elements: ✅ None
- Hidden lines: ✅ None (Pipeline emits 5 outgoing edges; lines route around boxes without going through them)
- Label readability: ✅ Pass
- Flow clarity: ✅ Clear (User → CLI → workflows → libs → externals, top to bottom)
- Dark mode: ✅ Saturated mid-tone fills (blue/green/purple); no near-white or near-black
```

### `docs/design/pipeline-process.md` — single-repo pipeline (N0-N6)

Rendered: `data/diagrams/pipeline.png` (94 KB)

```
**Mermaid Auto-Inspection:**
- Touching elements: ✅ None
- Hidden lines: ✅ None (3 arrows converge cleanly on Verdict rejected)
- Label readability: ✅ Pass
- Flow clarity: ✅ Clear (linear top-down with two decision branches: circuit-breaker, dry-run, HITL approve/reject, PR Preview submit/exit)
- Dark mode: ✅ Yellow gates for decisions, green for happy-path endpoints, red for rejection endpoints
```

### `docs/design/pipeline-process.md` — bulk-scan (Stage 0-4)

Rendered: `data/diagrams/bulkscan.png` (60 KB)

```
**Mermaid Auto-Inspection:**
- Touching elements: ✅ None
- Hidden lines: ✅ None
- Label readability: ✅ Pass
- Flow clarity: ✅ Clear (linear Stage 0→1→2→3→4→Report, with Resume entering Stage 0 via dashed edge)
- Dark mode: ✅ Stage 2 highlighted green to flag #230 persistence; abort path yellow; aborted endpoint yellow
```

### Style compliance (per AZ §4-5)

- All labels quoted (`<br/>` for line breaks; no raw newlines)
- No `#` outside quoted labels
- No `{}` in label text
- No `()` in unquoted edge labels
- Each diagram uses `flowchart TD` per §4.1

### Layout compliance (per AZ §7-8)

- §7.2 bidirectional flow: HITL Console uses TB layout with dashed response arrow back to Pipeline
- §7.4 cyclic flow: Resume → Stage 0 → ... avoids the cycle problem by using dashed entry into the same forward chain rather than a back-edge
- §8.1 simplicity: no near-duplicate nodes
- §8.2 no touching elements: confirmed in renders
- §8.3 no lines behind boxes: confirmed
- §8.6 dark mode: saturated mid-tone fills only

## Content verification

### README.md status table

Hand-checked against shipped PRs:

| Claim | Verified |
|---|---|
| Hostile-maintainer detection → Shipped | ✅ #184 merged 2026-05-13 |
| Anti-AI classifier → Shipped | ✅ #207 merged 2026-05-13 |
| Bulk-scan → Shipped | ✅ #219 + hotfixes #221/#225 merged 2026-05-13 |

### README.md subcommand table

`bulk-scan` row matches actual CLI:

```
$ poetry run python -m gh_link_auditor.cli.main bulk-scan --help
positional arguments:
  {start,status,stop,report,list-runs}
```

All five subcommands listed in the README.

### Bulk-scan-kickoff.md updates

- #230 reference: prose accurate; matches `bulk_scan/runner.py:run_liveness` cache-first behavior shipped in PR #232.
- #231 reference: `--new-run` flag exists in `cli/bulk_scan_cmd.py` shipped in PR #233. Quoted error/suggestion behavior matches the tested code paths in `tests/unit/cli/test_bulk_scan_cmd.py::TestCmdStartRunIdGate`.

### Link integrity

Internal markdown links checked manually:
- `docs/design/` references → resolve
- `docs/runbooks/operator-guide.md` cross-link from architecture.md → resolves
- `docs/runbooks/bulk-scan-kickoff.md` cross-link from operator-guide.md → resolves
- `feedback-one-link-pr-policy` reference in kickoff → matches the memory in `~/.claude/.../memory/feedback_one_link_pr_policy.md`

## Results

| Check | Result |
|---|---|
| Mermaid diagrams render | ✅ 3/3 |
| Mermaid §8.4 checklist | ✅ All pass |
| README claims match shipped PRs | ✅ Verified |
| Internal links resolve | ✅ All checked |
| Ruff (no Python changes) | N/A |
| Test suite (no Python changes) | N/A |
