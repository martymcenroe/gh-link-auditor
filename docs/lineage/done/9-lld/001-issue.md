---
repo: martymcenroe/gh-link-auditor
issue: 9
url: https://github.com/martymcenroe/gh-link-auditor/issues/9
fetched: 2026-02-16T17:21:02.874465Z
---

# Issue #9: feat: Implement Request Wrapper Module

Create a core `network.py` module to abstract `urllib` complexity and header management.

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

## Reference: docs\standards\00007-anti-bot-backoff.md

```
# 00007 — Anti-Bot Backoff Algorithm

**Status:** Accepted
**Issue:** #7
**Created:** 2026-02-16

---

## Overview

Defines the retry and backoff strategy for handling rate-limited (429) and anti-bot (403/405) responses when checking URLs.

## Strategy

**Exponential backoff with jitter** — the standard approach for respectful automated HTTP clients.

## Algorithm

```
delay = min(base_delay * (2 ^ attempt) + random_jitter, max_delay)
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `base_delay` | `1.0s` | Initial delay before first retry |
| `max_delay` | `30.0s` | Hard ceiling on any single delay |
| `max_retries` | `2` | Total retry attempts (3 total requests max) |
| `jitter_range` | `0.0–1.0s` | Random uniform jitter added to each delay |

### Retry Schedule (defaults)

| Attempt | Base Delay | With Jitter (range) |
|---------|-----------|---------------------|
| 1st retry | 2.0s | 2.0–3.0s |
| 2nd retry | 4.0s | 4.0–5.0s |

## Trigger Conditions

### Always Retry

| Status | Meaning | Action |
|--------|---------|--------|
| `429` | Too Many Requests | Retry with backoff. Honor `Retry-After` header if present. |
| `503` | Service Unavailable | Retry with backoff |
| Timeout | Connection/read timeout | Retry with backoff |
| Connection reset | Remote disconnected | Retry with backoff |

### Retry Once (Fallback to GET)

| Status | Meaning | Action |
|--------|---------|--------|
| `405` | Method Not Allowed | Retry once with `GET` instead of `HEAD` |
| `403` | Forbidden | Retry once with `GET` (some servers block HEAD only) |

### Never Retry

| Status | Meaning | Action |
|--------|---------|--------|
| `404` | Not Found | Report as broken immediately |
| `410` | Gone | Report as broken immediately |
| `200–399` | Success/redirect | Report as OK |
| DNS failure | Unresolvable host | Report as failed immediately |

## Retry-After Header

When a `429` response includes a `Retry-After` header:

1. If the value is an integer (seconds), use `max(retry_after_value, calculated_delay)`
2. If the value is an HTTP-date, compute seconds until that time
3. If the header is absent, use the calculated exponential delay
4. Cap at `max_delay` regardless of header value

## Request Flow

```
1. Send HEAD request
2. If 405 or 403 → retry with GET (one attempt)
3. If 429/503/timeout/reset → apply backoff, retry up to max_retries
4. If still failing after all retries → report final status
```

## Per-Domain Rate Limiting

To avoid hammering a single host:

- Track last request time per domain
- Enforce minimum 500ms between requests to the same domain
- This is separate from retry backoff — it applies to all requests

## Implementation Notes

- Jitter prevents thundering herd when scanning many URLs from the same domain
- The HEAD → GET fallback (for 403/405) counts as one attempt, not a retry
- All delays are non-blocking per-URL (other URLs can be checked during waits when concurrency is added)
- Log every retry at DEBUG level with: URL, attempt number, delay, status code

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