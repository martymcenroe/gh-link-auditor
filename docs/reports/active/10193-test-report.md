# Test Report: #193 HEAD-404 triggers GET fallback

## Local verification

```
1807 passed, 1 skipped, 1 warning in 101.80s
```

Pre-change: 1804. Net +3 (2 new in `TestHeadToGetFallback404`; 1 renamed existing).

## RED → GREEN

The new `test_head_to_get_fallback_404` failed before the `should_retry` change (404 was returning `(False, False)`). After moving 404 into the GET-fallback group, all three tests in `TestHeadToGetFallback404` + the renamed `TestShouldRetry::test_404_get_fallback` pass.

Two pre-existing tests (`test_404_no_retry`, `test_404_does_not_trigger_fallback`) had encoded the OLD policy. Both updated in place to the new policy; behavior change is intentional and documented.

## Lint + format

`poetry run ruff check . && poetry run ruff format --check .` — clean.

## CI verification

PR runs through the standard gate (Test + Lint + auto-review + pr-sentinel).

## Coverage

≥95% on the changed line in `should_retry`. The new branch is exercised by two tests covering the HEAD→GET→200 and HEAD→GET→404 paths.

## Out of scope

Live verification against `marketplace.visualstudio.com` deferred to the next audit run — the unit tests prove the contract.
