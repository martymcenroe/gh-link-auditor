# Test Report: Clone-Last Architecture (#67)

## Summary

| Metric | Value |
|--------|-------|
| Tests collected | 1134 |
| Tests passed | 1121 |
| Tests skipped | 1 |
| Tests failed | 0 |
| Overall coverage | 97% |
| `github_api.py` coverage | 100% |
| `n0_load_target.py` coverage | 100% |
| `n1_scan.py` coverage | 97% |
| `n5_generate_fix.py` coverage | 85% |
| `state.py` coverage | 100% |
| Lint | All checks passed |

## New Tests Added (40 total)

### `tests/unit/test_github_api.py` (20 tests)
- FakeGitHubContentsClient: 8 tests (filtering, sorting, content, error handling, call tracking)
- GitHubContentsClient: 12 tests (flat repo, subdirectories, empty repo, base64 decode, 404/500 errors, auth headers, close)

### `tests/unit/pipeline/test_n0.py` (7 new tests)
- URL target lists doc files via fake client
- URL target returns empty for repos with no docs
- URL target returns empty for bad URLs
- N0 node sets repo_owner/repo_name_short for URL targets
- N0 node sets empty owner for local targets
- `_extract_owner_repo()`: 4 tests (GitHub, GitLab, short URL, trailing slash)

### `tests/unit/pipeline/test_n1.py` (9 new tests)
- `_read_file_content()`: local file, remote file, missing local, missing remote
- `_extract_urls_from_file()` URL target: extracts URLs, handles missing files
- `run_link_scan()` URL target: scans remote files via fake client

### `tests/unit/pipeline/test_n5.py` (4 new tests)
- URL target triggers clone and generates diff
- URL target skips when no approved verdicts
- URL target errors on missing owner/repo
- URL target errors on clone failure

## Testing Approach

- **FakeGitHubContentsClient** for pipeline node tests (dependency injection)
- **httpx MockTransport** for real GitHubContentsClient tests
- **unittest.mock.patch** only for `_clone_repo` in N5 (git operations)
- Zero MagicMock in all new tests
