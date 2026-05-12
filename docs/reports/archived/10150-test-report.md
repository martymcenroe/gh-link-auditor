# Test Report: #150 Automated Maintainer Blacklisting

## Test File
`tests/unit/test_auto_blacklist.py` — 15 tests

## Coverage Areas

| Class | Tests | Coverage |
|-------|-------|----------|
| TestGetBlacklistBySource | 3 | empty, grouped, expired excluded |
| TestAutoBlacklistFixStolen | 2 | blacklists on fix, no blacklist on normal close |
| TestUnresponsiveTimeout | 3 | 30+ days, <30 days, no duplicates |
| TestN0BlacklistCheck | 2 | blacklisted aborts, clean proceeds |
| TestBlacklistCli | 5 | list empty, add+list, remove, remove nonexistent, stats |

## Results
- 15/15 pass
- Full suite: 1578 passed, 1 skipped
- No regressions
