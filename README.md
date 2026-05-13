# gh-link-auditor

**Autonomous broken-link audit and PR-fix pipeline for documentation across GitHub repositories.**

`gh-link-auditor` (CLI prefix `ghla`) scans a repository's docs for dead links, asks an LLM to suggest replacements, runs the suggestions through a verification gate, and — for repos where you've opted in — forks the upstream, applies the fixes, and opens a pull request from the fork. State, blacklist, metrics, and trust escalation live in a single SQLite database (`~/.ghla/ghla.db`).

## Status

| Capability | State |
|---|---|
| Link integrity audit (HTTP/HTTPS, redirects, archive fallback) | Shipped |
| LangGraph pipeline (N0 load → N1 scan → N2 investigate → N3 score → N4 HITL → N5 fix → N6 submit PR) | Shipped |
| Human-in-the-Loop console (review/submit/exit per finding) | Shipped |
| Fork → fix → PR submission workflow | Shipped |
| Unified SQLite state DB (interactions, blacklist, metrics, snooze queue, trust) | Shipped |
| Trust-based PR escalation (new → tier1_pending → tier1_proven → tier2_eligible) | Shipped |
| Auto-blacklist on repo unresponsiveness (PRs ignored for N days) | Shipped |
| Snooze + recheck queue for ambiguous findings | Shipped |
| Batch engine (run pipeline across many repos with rate limits) | Shipped |
| Campaign metrics dashboard (`ghla metrics campaign`) | Shipped |
| Repo discovery via stargazer harvesting | Shipped |
| Hostile-maintainer comment detection + auto-blacklist | Planned (#178) |

## Quickstart

```bash
git clone https://github.com/martymcenroe/gh-link-auditor
cd gh-link-auditor
poetry install
poetry run python -m gh_link_auditor.cli.main run https://github.com/<owner>/<repo>
```

This is a dry run by default — N0 through N3 only. Add `--dry-run=false` (or omit the flag) for the full pipeline including HITL and PR submission.

### Subcommands

| Command | Purpose |
|---|---|
| `ghla run <target>` | Run the full pipeline against one repo URL or local clone |
| `ghla batch <yaml-config>` | Run the pipeline across many repos with rate limiting |
| `ghla blacklist {list,add,remove,stats}` | Manage the repo blacklist |
| `ghla metrics {campaign,refresh,scan-history}` | Show campaign dashboard and refresh PR statuses |
| `ghla recheck` | Process snoozed findings due for re-verification |

(`ghla` here is shorthand for `poetry run python -m gh_link_auditor.cli.main`.)

### Standalone scripts

Two zero-dep scripts at the repo root pre-date the unified CLI and remain for ad-hoc use:

- `check_links.py` — scan one file or directory, report dead links, exit code = number found.
- `hitl_console.py` — interactive review of in-flight findings from the DB.

## Configuration

- `~/.ghla/ghla.db` — unified SQLite store; auto-created on first write. Override with `--db-path` on any subcommand.
- `.env` — loaded at CLI start via `python-dotenv`. Use it for `GITHUB_TOKEN`, `ANTHROPIC_API_KEY`, etc.

## Documentation

- [`docs/lld/`](docs/lld/) — low-level designs (active + archived)
- [`docs/adrs/`](docs/adrs/) — architecture decision records
- [`docs/reports/`](docs/reports/) — per-issue implementation and test reports
- [`CLAUDE.md`](CLAUDE.md) — project-specific rules for agents working on this codebase

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Sponsorship

If this tool saves you time, please consider [sponsoring the development](https://github.com/sponsors/martymcenroe).
