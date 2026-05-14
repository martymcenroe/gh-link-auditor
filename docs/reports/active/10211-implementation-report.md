# Implementation Report — #211 (SE-network allow-list)

**Branch:** `211-se-allowlist`
**LLD:** `docs/lld/active/LLD-211.md`

## Summary

Categorical skip for Stack Exchange network URLs at N1's pre-check layer. SE URLs are never probed; never surface as dead links; never reach N4 HITL.

## Changes

| File | Action |
|---|---|
| `src/gh_link_auditor/false_positives.py` | Added `ALWAYS_ALIVE_DOMAINS` set + `is_always_alive_domain(url) -> bool`. Wired into `is_false_positive` master check. |
| `src/gh_link_auditor/pipeline/nodes/n1_scan.py` | Pre-check expanded to call `is_always_alive_domain` alongside the existing placeholder/API-test checks. |
| `tests/unit/test_false_positives.py` | 21 new tests for `is_always_alive_domain` + 3 tests for the integration with `is_false_positive`. One existing test (`test_bot_blocked_without_status`) updated to reflect new behavior. |
| `docs/lld/active/LLD-211.md` | Spec. |

## Allow-list

```python
ALWAYS_ALIVE_DOMAINS = {
    "stackoverflow.com",
    "stackexchange.com",   # plus every *.stackexchange.com subdomain
    "serverfault.com",
    "superuser.com",
    "askubuntu.com",
    "mathoverflow.net",
    "stackapps.com",
}
```

Subdomain matching via `hostname.endswith(f".{domain}")` — `physics.stackexchange.com` matches `stackexchange.com`. The leading dot prevents typosquat matches (`stackoverflow-clone.com` does NOT match `stackoverflow.com`).

Case-insensitive on the host portion.

## Behavior change

Before: `is_false_positive("https://stackoverflow.com/q/1")` returned `False` (required a 403/429 status to flag via `is_bot_blocked`).

After: returns `True` regardless of status. The `test_bot_blocked_without_status` assertion was inverted to reflect this — comment marks it as an intentional #211 change.

Non-SE bot-blocked domains (medium.com, quora.com, etc.) unchanged: still need a status code to be flagged.

## Pre-flight context

This change is the gating prerequisite for the 7,500-repo bulk Python doc scan planned for 2026-05-14 → 2026-05-19. Without it, every Python docs repo throws 50-200 SO false positives, drowning the signal-to-noise.

## Test summary

- 24 new tests in `test_false_positives.py` (21 for the new function, 3 for the master integration)
- 1 inverted test (`test_bot_blocked_without_status`)
- Full suite: **1950 passed**, 1 skipped, 0 failed (up from 1925 baseline)
- ruff format + check clean

## Acceptance checklist

- [x] `is_always_alive_domain` exists and exported
- [x] N1 pre-check covers SE network
- [x] Typosquat domains (stackoverflow-clone.com) do NOT match
- [x] Hostname matching is case-insensitive
- [x] `is_false_positive` master includes the new check
- [x] All 7 SE-network domains tested
- [x] Subdomains tested (physics, unix, security)
- [x] Full suite green
