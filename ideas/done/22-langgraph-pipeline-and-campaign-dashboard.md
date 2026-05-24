# Pipeline and Run-Metrics Dashboard (Historical)

This was an early planning doc for stitching the gh-link-auditor pipeline together under LangGraph and adding a run-metrics dashboard. The full original design and motivation has been moved to `docs/private/dashboard-spec.md` (gitignored) per #278; the operator's notes there carry historical context that doesn't belong on the public surface.

What shipped from this design:

- LangGraph pipeline (N0 load → N1 scan → N2 investigate → N3 score → N4 HITL → N5 fix → N6 submit PR) — see [`docs/design/`](../../docs/design/)
- Pipeline run-metrics dashboard via the `ghla metrics campaign` subcommand — see `src/gh_link_auditor/campaign_dashboard.py`
- Run-status tracking persisted in the unified SQLite store (`~/.ghla/ghla.db`)

Labels: epic, langgraph, pipeline, dashboard
