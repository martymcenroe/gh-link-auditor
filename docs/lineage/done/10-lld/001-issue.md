---
repo: martymcenroe/gh-link-auditor
issue: 10
url: https://github.com/martymcenroe/gh-link-auditor/issues/10
fetched: 2026-02-16T17:27:06.106192Z
---

# Issue #10: feat: Interactive Console UI (HITL) Loop

Implement the `input()` loop for the 'Human-in-the-Loop' resolution mode.

---

# Context Files

## Reference: check_links.py

```
import http.client
import re
import ssl
import time
import urllib.error
import urllib.request


def find_urls(filepath: str) -> list[str]:
    """Extracts all HTTP/HTTPS URLs from a file."""
    print(f"--- Locating URLs in {filepath} ---")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"ERROR: Could not read file: {e}")
        return []

    # Regex to find URLs, including those in markdown parens
    # It avoids matching the final parenthesis if it''s part of the markdown
    url_regex = re.compile(r"https?://[a-zA-Z0-9./?_&%=\-~:#]+")

    urls = url_regex.findall(content)
    unique_urls = sorted(list(set(urls)))
    print(f"Found {len(unique_urls)} unique URLs.")
    return unique_urls


def check_url(url: str, retries: int = 2) -> str:
    """
    Checks a single URL. Returns a status string.
    Uses a standard User-Agent to avoid 403 Forbidden errors.
    """
    # Create a default SSL context that does not verify certs
    # This helps avoid SSL certificate verification errors, which are common
    # but don''t necessarily mean the link is "broken" for our purposes.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/58.0.3029.110 Safari/537.36"
        )
    }

    req = urllib.request.Request(url, headers=headers, method="HEAD")

    for attempt in range(retries):
        try:
            # Set a 10-second timeout
            with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                return f"[  OK  ] (Code: {response.status}) - {url}"
        except urllib.error.HTTPError as e:
            # Server responded, but with an error code (404, 403, 500, etc.)
            return f"[ ERROR ] (Code: {e.code}) - {url}"
        except urllib.error.URLError as e:
            # URL-related error (e.g., DNS failure, timeout)
            if "timed out" in str(e.reason):
                if attempt < retries - 1:
                    time.sleep(1)  # Wait before retry
                    continue  # Try again
                return f"[ TIMEOUT ] - {url}"
            return f"[ FAILED ] (Reason: {e.reason}) - {url}"
        except (http.client.RemoteDisconnected, ConnectionResetError):
            if attempt < retries - 1:
                time.sleep(1)
                continue
            return f"[ DISCONNECTED ] - {url}"
        except Exception as e:
            # Catch-all for other issues (e.g., invalid URL format)
            return f"[ INVALID ] (Error: {type(e).__name__}) - {url}"

    return f"[ FAILED ] (All retries) - {url}"


def main():
    """Main function to check all URLs in README.md."""
    filepath = "README.md"
    urls_to_check = find_urls(filepath)

    if not urls_to_check:
        print("No URLs found to check.")
        return

    print("\n--- Starting URL Validation ---")

    error_count = 0
    for url in urls_to_check:
        status = check_url(url)
        print(status)
        if "ERROR" in status or "FAILED" in status or "TIMEOUT" in status or "INVALID" in status:
            error_count += 1

    print("--- Validation Complete ---")
    if error_count == 0:
        print("All links are valid.")
    else:
        print(f"Found {error_count} potential issues.")


if __name__ == "__main__":
    main()

```

## Reference: docs\standards\00006-cli-argument-parser.md

```
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

```

## Reference: docs\standards\00008-json-report-schema.md

```
# 00008 — JSON Report Schema

**Status:** Accepted
**Issue:** #8
**Created:** 2026-02-16

---

## Overview

Defines the structured JSON output format for link audit results. This schema is the data contract between the scanner, HITL resolution mode, and the planned Doc-Fix Bot.

## Schema Version

`1.0.0` — uses semantic versioning. Breaking changes increment major version.

## Top-Level Structure

```json
{
  "schema_version": "1.0.0",
  "audit": {
    "timestamp": "2026-02-16T14:30:00Z",
    "duration_seconds": 12.4,
    "tool_version": "0.1.0"
  },
  "source": {
    "files": ["README.md", "CONTRIBUTING.md"],
    "total_urls": 42,
    "unique_urls": 38
  },
  "summary": {
    "ok": 35,
    "error": 2,
    "timeout": 1,
    "failed": 0,
    "disconnected": 0,
    "invalid": 0
  },
  "results": [...]
}
```

## Field Definitions

### `audit` — Metadata

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string (ISO 8601) | When the scan started |
| `duration_seconds` | float | Total scan wall-clock time |
| `tool_version` | string (semver) | Version of gh-link-auditor |

### `source` — Input Summary

| Field | Type | Description |
|-------|------|-------------|
| `files` | string[] | Files that were scanned |
| `total_urls` | int | Total URL occurrences found (including duplicates) |
| `unique_urls` | int | Unique URLs checked |

### `summary` — Aggregate Counts

| Field | Type | Description |
|-------|------|-------------|
| `ok` | int | URLs returning 2xx/3xx |
| `error` | int | URLs returning 4xx/5xx |
| `timeout` | int | URLs that timed out after all retries |
| `failed` | int | URLs with connection/DNS failures |
| `disconnected` | int | Remote disconnected |
| `invalid` | int | Malformed URLs or unexpected errors |

### `results` — Per-URL Details

Each entry in the `results` array:

```json
{
  "url": "https://example.com/page",
  "status": "ok",
  "status_code": 200,
  "method": "HEAD",
  "response_time_ms": 234,
  "retries": 0,
  "found_in": [
    {
      "file": "README.md",
      "line": 15
    }
  ],
  "error": null,
  "resolution": null
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | yes | The checked URL |
| `status` | string | yes | One of: `ok`, `error`, `timeout`, `failed`, `disconnected`, `invalid` |
| `status_code` | int \| null | yes | HTTP status code, or `null` if no response received |
| `method` | string | yes | HTTP method used: `HEAD` or `GET` (after fallback) |
| `response_time_ms` | int \| null | yes | Response time in milliseconds, or `null` on failure |
| `retries` | int | yes | Number of retry attempts made |
| `found_in` | object[] | yes | List of file locations where this URL appears |
| `found_in[].file` | string | yes | File path |
| `found_in[].line` | int | yes | Line number |
| `error` | string \| null | yes | Error description if status is not `ok`, else `null` |
| `resolution` | object \| null | yes | HITL resolution data (see below), `null` if unresolved |

### `resolution` — HITL Resolution (when present)

```json
{
  "action": "replace",
  "new_url": "https://example.com/new-page",
  "resolved_by": "human",
  "resolved_at": "2026-02-16T15:00:00Z",
  "note": "Page moved to new location"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `action` | string | One of: `replace`, `remove`, `ignore`, `keep` |
| `new_url` | string \| null | Replacement URL (for `replace` action) |
| `resolved_by` | string | `human` or `llm` |
| `resolved_at` | string (ISO 8601) | When the resolution was made |
| `note` | string \| null | Optional note explaining the resolution |

## Status Values

| Status | When assigned |
|--------|-------------|
| `ok` | HTTP 2xx or 3xx response |
| `error` | HTTP 4xx or 5xx response |
| `timeout` | No response within timeout after all retries |
| `failed` | Connection/DNS failure |
| `disconnected` | Remote server closed connection |
| `invalid` | Malformed URL or unexpected exception |

## File Naming Convention

- Default output: `scan_results.json`
- Timestamped: `scan_results_2026-02-16T143000Z.json`
- Custom via `--output` flag (see 00006)

## Compatibility Notes

- The `resolution` field is always present but `null` until HITL mode populates it
- The `found_in` array supports a URL appearing in multiple files/locations
- Downstream consumers (Doc-Fix Bot) should check `schema_version` before parsing
- New fields may be added in minor versions; consumers should ignore unknown fields

```