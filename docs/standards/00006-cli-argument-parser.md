# 00006 — CLI Argument Parser Specification

**Status:** Accepted
**Issue:** #6
**Created:** 2026-02-16

---

## Overview

Defines the command-line interface for `gh-link-auditor` using Python's `argparse` with flat flags (no subcommands).

## Usage

```bash
python check_links.py [OPTIONS] [FILES...]
```

## Positional Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `FILES` | `README.md` | One or more files or glob patterns to scan for URLs |

## Flags

### Core Operations

| Flag | Short | Type | Default | Description |
|------|-------|------|---------|-------------|
| `--scan` | `-s` | bool | `true` | Run link scan (default action) |
| `--resolve` | `-r` | bool | `false` | Enter HITL interactive resolution mode after scan |
| `--output` | `-o` | str | `stdout` | Write JSON report to file path |

### Request Behavior

| Flag | Short | Type | Default | Description |
|------|-------|------|---------|-------------|
| `--timeout` | `-t` | int | `10` | Per-request timeout in seconds |
| `--retries` | | int | `2` | Max retry attempts per URL |
| `--delay` | | float | `1.0` | Base delay between retries in seconds |
| `--user-agent` | | str | *(Chrome UA)* | Custom User-Agent header |
| `--no-verify-ssl` | | bool | `true` | Skip SSL certificate verification |

### Filtering

| Flag | Short | Type | Default | Description |
|------|-------|------|---------|-------------|
| `--include` | | str | `*` | URL pattern to include (glob) |
| `--exclude` | | str | `""` | URL pattern to exclude (glob) |
| `--status` | | str | `all` | Filter report by status: `ok`, `error`, `timeout`, `failed`, `all` |

### Output Control

| Flag | Short | Type | Default | Description |
|------|-------|------|---------|-------------|
| `--format` | `-f` | str | `text` | Output format: `text`, `json`, `markdown` |
| `--verbose` | `-v` | bool | `false` | Show detailed request/response info |
| `--quiet` | `-q` | bool | `false` | Suppress all output except errors |

### Meta

| Flag | Type | Description |
|------|------|-------------|
| `--version` | bool | Show version and exit |
| `--help` | bool | Show help and exit |

## Examples

```bash
# Scan README.md (default)
python check_links.py

# Scan specific files
python check_links.py docs/*.md CONTRIBUTING.md

# Scan and output JSON report
python check_links.py --output report.json --format json

# Scan with HITL resolution
python check_links.py --resolve

# Show only broken links
python check_links.py --status error

# Custom timeout and retries
python check_links.py --timeout 30 --retries 5
```

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All links valid |
| `1` | One or more broken links found |
| `2` | Invalid arguments or runtime error |

## Implementation Notes

- When no flags are provided, `--scan` is the implicit default action
- `--resolve` implies `--scan` (scan runs first, then resolution mode opens)
- `--quiet` and `--verbose` are mutually exclusive
- `--output` with `--format json` writes the JSON report schema defined in 00008
- Glob patterns in `FILES` are expanded by the shell, not by argparse
