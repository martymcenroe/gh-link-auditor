# Implementation Report: #198 stealth fallback for CDN-fronted None status

## Summary

Today's python-guide finding #7 (`https://www.pythonjobshq.com`): probe returned status `None` (transport-level error), pipeline declared dead. The site is actually live — Cloudflare-protected (resolves to 104.17.x.x), serves real content to browsers.

`#190` shipped stealth fallback only for `status_code == 403`. The `None` status path bypassed stealth entirely. This PR adds a second branch: when `status_code is None` AND `error_type in {"connection_reset", "timeout"}` AND the host resolves to a known CDN range, invoke `_headless_browser_get`.

See LLD-198.

## Changes

### `src/gh_link_auditor/network.py`

- New imports: `ipaddress`, `urlparse`.
- New module-level tuple `_CDN_RANGES` covering Cloudflare main blocks (`104.16.0.0/12`, `172.64.0.0/13`) and Fastly (`151.101.0.0/16`, `199.232.0.0/16`). Akamai deliberately excluded — vast and frequently changing.
- New helper `_resolves_to_cdn(url) -> bool`: parses hostname, resolves via `socket.gethostbyname_ex`, checks each returned IP against `_CDN_RANGES`. Returns `False` on DNS failure / no hostname / non-CDN IP. ~5-50ms typical (OS resolver cache).
- New stealth-fallback branch in `check_url` after the existing 403-stealth branch: fires only when `status_code is None`, error is transport-class, opt-in flag set, AND host is CDN-fronted.

The new branch is bounded by the same `request_config.get("allow_headless")` flag that gates #190 — N1 enables it; N2's per-candidate probes leave it off.

### `tests/unit/test_network.py`

- New `TestResolvesToCDN` (5 tests): Cloudflare IP, Fastly IP, non-CDN IP, DNS failure, no-hostname URL.
- New `TestHeadlessFallbackOnNone` (3 tests): fires on `ConnectionResetError` when CDN; skips when not CDN; skips when `allow_headless=False`.

## Files modified

| File | Change |
|------|--------|
| `src/gh_link_auditor/network.py` | `_resolves_to_cdn` helper + None-status branch in `check_url` |
| `tests/unit/test_network.py` | 8 new tests across 2 new classes |
| `docs/lld/active/LLD-198.md` | NEW design |

## Test count

`pytest --co -q` collects **1828 tests** post-change (was 1820, +8 net).

## Operator impact

`pythonjobshq.com` and similar Cloudflare-fronted URLs that get connection-reset on bot probes will now be verified via real browser. False-positive class closed.

Cost: one extra DNS lookup per dead-link probe (~5-50ms cached). Stealth itself (~10-20s) only fires when the lookup confirms CDN — non-CDN dead URLs short-circuit immediately.

## Out of scope

- Akamai range coverage (separate research).
- Reverse-DNS / SNI-based CDN detection.
- Configurable CDN ranges via env or config file (hardcoded list is fine for now; update as we learn).
