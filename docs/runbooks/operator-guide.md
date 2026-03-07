# Operator Guide: Running gh-link-auditor

## Overview

gh-link-auditor finds dead links in GitHub repositories and generates fixes. The workflow is:

1. **Discover** repos to audit (repo-scout)
2. **Audit** a single repo (ghla run)
3. **Batch audit** many repos (ghla batch)
4. **Review** metrics (ghla metrics)

## Prerequisites

### 1. Create your .env file

```bash
cp .env.example .env
```

Edit `.env` with your actual values:

```
GITHUB_TOKEN=github_pat_your_token_here
LLM_MODEL_NAME=gpt-4o-mini
```

- `GITHUB_TOKEN` — your Fine-Grained PAT (see AssemblyZero runbook 0925)
- `LLM_MODEL_NAME` — the model used for link investigation and fix generation (default: `gpt-4o-mini`)

### 2. Verify installation

```bash
cd /c/Users/mcwiz/Projects/gh-link-auditor
poetry run python -c "from dotenv import load_dotenv; load_dotenv(); print('ready')"
```

---

## Step 1: Discover Repos (repo-scout)

Repo Scout finds interesting GitHub repos to audit. You need at least one discovery source.

### Quick start — discover from stargazers

Find repos starred by people who starred a popular tool:

```bash
poetry run python -c "
from repo_scout.cli import main
import sys
sys.exit(main([
    '--seed-repos', 'anthropics/claude-code',
    '--max-stargazers', '50',
    '--max-repo-age-months', '6',
    '--output', 'targets.json',
    '--format', 'json'
]))
"
```

### Discover from Awesome lists

```bash
poetry run python -c "
from repo_scout.cli import main
import sys
sys.exit(main([
    '--awesome-lists', 'sindresorhus/awesome',
    '--output', 'targets.json',
    '--format', 'json'
]))
"
```

### Discover from starred repos (star walking)

```bash
poetry run python -c "
from repo_scout.cli import main
import sys
sys.exit(main([
    '--root-users', 'martymcenroe',
    '--star-depth', '2',
    '--output', 'targets.json',
    '--format', 'json'
]))
"
```

### Combine multiple sources

```bash
poetry run python -c "
from repo_scout.cli import main
import sys
sys.exit(main([
    '--seed-repos', 'anthropics/claude-code', 'langchain-ai/langchain',
    '--awesome-lists', 'sindresorhus/awesome',
    '--root-users', 'martymcenroe',
    '--max-stargazers', '50',
    '--star-depth', '2',
    '--output', 'targets.json',
    '--format', 'json'
]))
"
```

**Output:** `targets.json` — a list of repo records sorted by relevance.

---

## Step 2: Audit a Single Repo (ghla run)

### Dry run first (no PRs, just find dead links)

```bash
poetry run python -c "
from gh_link_auditor.cli.main import main
import sys
sys.exit(main(['run', 'https://github.com/OWNER/REPO', '--dry-run', '--verbose']))
"
```

### Full run (generates fixes)

```bash
poetry run python -c "
from gh_link_auditor.cli.main import main
import sys
sys.exit(main(['run', 'https://github.com/OWNER/REPO', '--verbose']))
"
```

### Options

| Flag | Default | What it does |
|------|---------|-------------|
| `--dry-run` | off | Find dead links only, no fixes |
| `--max-links` | 50 | Circuit breaker: stop if more than N dead links |
| `--max-cost` | 5.00 | Cost limit in USD for LLM calls |
| `--confidence` | 0.8 | Min confidence for auto-approval (below = human review) |
| `--verbose` | off | Detailed logging |
| `--db-path` | auto | Path to state database |

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error |
| 2 | Circuit breaker triggered (too many dead links) |
| 3 | Cost limit reached |

---

## Step 3: Batch Audit (ghla batch)

Audit many repos from a target list (output of repo-scout).

### Run a batch

```bash
poetry run python -c "
from gh_link_auditor.cli.main import main
import sys
sys.exit(main([
    'batch', 'run',
    '--target-list', 'targets.json',
    '--dry-run',
    '--max-repos', '5'
]))
"
```

### Resume a failed batch

```bash
poetry run python -c "
from gh_link_auditor.cli.main import main
import sys
sys.exit(main(['batch', 'resume', '--checkpoint', 'data/checkpoints/BATCH_ID.json']))
"
```

### Check batch status

```bash
poetry run python -c "
from gh_link_auditor.cli.main import main
import sys
sys.exit(main(['batch', 'status', '--checkpoint', 'data/checkpoints/BATCH_ID.json']))
"
```

### Batch options

| Flag | Default | What it does |
|------|---------|-------------|
| `--target-list` | required | Path to repo-scout JSON output |
| `--concurrency` | 1 | Number of parallel workers |
| `--dry-run` | off | Skip PR submission |
| `--max-repos` | all | Cap on repos to process |

---

## Step 4: Campaign Metrics

View aggregate metrics across all runs.

```bash
poetry run python -c "
from gh_link_auditor.cli.main import main
import sys
sys.exit(main(['metrics', 'campaign']))
"
```

---

## Recommended First Run

If you've never run this before, do this:

```bash
# 1. Set up .env
cp .env.example .env
# Edit .env with your token

# 2. Discover 5 repos from stargazers of a popular project
poetry run python -c "
from repo_scout.cli import main
import sys
sys.exit(main([
    '--seed-repos', 'anthropics/claude-code',
    '--max-stargazers', '20',
    '--output', 'targets.json',
    '--format', 'json'
]))
"

# 3. Dry-run audit the first target to see what it finds
# (read targets.json to pick a repo URL, then:)
poetry run python -c "
from gh_link_auditor.cli.main import main
import sys
sys.exit(main(['run', 'https://github.com/OWNER/REPO', '--dry-run', '--verbose']))
"

# 4. If that looks good, run the batch (dry-run, 3 repos max)
poetry run python -c "
from gh_link_auditor.cli.main import main
import sys
sys.exit(main([
    'batch', 'run',
    '--target-list', 'targets.json',
    '--dry-run',
    '--max-repos', '3'
]))
"
```

---

## Pipeline Stages (what happens inside ghla run)

| Node | Name | What it does |
|------|------|-------------|
| N0 | Load Target | Clone/fetch the repo, inventory markdown files |
| N1 | Scan | Extract all URLs from markdown, check each one |
| N2 | Investigate | LLM analyzes dead links for root cause |
| N3 | Judge | LLM generates fix verdicts with confidence scores |
| N4 | Human Review | Interactive review for low-confidence verdicts |
| N5 | Generate Fix | Produce diff/PR content for approved fixes |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError` | Run from project root with `poetry run` |
| 401 from GitHub API | Token expired or missing — check `.env` |
| Circuit breaker triggers immediately | Repo has many dead links — raise `--max-links` or pick a different repo |
| Cost limit reached | Raise `--max-cost` or use a cheaper model in `.env` |
| No dead links found | Good news — the repo is clean |
