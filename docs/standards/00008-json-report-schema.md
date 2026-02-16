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
