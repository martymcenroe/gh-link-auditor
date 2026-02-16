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
