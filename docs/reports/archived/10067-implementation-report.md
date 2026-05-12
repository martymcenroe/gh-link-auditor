# Implementation Report: Clone-Last Architecture (#67)

## Summary

Implemented clone-last architecture so the pipeline can audit GitHub URL targets without cloning first. N0 and N1 use the GitHub Contents API to list and read documentation files remotely. Cloning only happens in N5 when approved fixes need to be applied to local files.

## Changes

| File | Type | Description |
|------|------|-------------|
| `src/gh_link_auditor/github_api.py` | NEW | GitHubContentsClient — Contents API wrapper for listing and fetching files |
| `src/gh_link_auditor/pipeline/nodes/n0_load_target.py` | MODIFIED | URL targets now list doc files via API; added `_extract_owner_repo()` |
| `src/gh_link_auditor/pipeline/nodes/n1_scan.py` | MODIFIED | Content fetcher abstraction (`_read_file_content()`) for local vs API |
| `src/gh_link_auditor/pipeline/nodes/n5_generate_fix.py` | MODIFIED | Clone-on-demand for URL targets; `_clone_repo()` helper |
| `src/gh_link_auditor/pipeline/state.py` | MODIFIED | Added `repo_owner` and `repo_name_short` fields |
| `tests/fakes/github_api.py` | NEW | FakeGitHubContentsClient |
| `tests/unit/test_github_api.py` | NEW | 20 tests for real + fake client |
| `tests/unit/pipeline/test_n0.py` | MODIFIED | 7 new tests for URL target handling |
| `tests/unit/pipeline/test_n1.py` | MODIFIED | 9 new tests for remote file reading |
| `tests/unit/pipeline/test_n5.py` | MODIFIED | 4 new tests for clone-on-demand |

## Design Decisions

1. **Contents API only** — no Trees/Blobs API (avoids SHA requirement)
2. **Dependency injection** via `github_client` parameter — enables fake injection in tests
3. **Graceful degradation** — API errors return empty lists rather than crashing N0
4. **httpx MockTransport** for real client tests — no MagicMock used

## LLD Deviation

None. Implementation follows LLD-067 as written.
