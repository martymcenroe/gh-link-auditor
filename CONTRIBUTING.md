# Contributing to gh-link-auditor

Thanks for your interest. Pull requests from the community are welcome.

## Development setup

```bash
git clone https://github.com/martymcenroe/gh-link-auditor
cd gh-link-auditor
poetry install
poetry run python -m pytest
```

`poetry install` resolves Python 3.10+ runtime deps plus dev deps (`pytest`, `pytest-cov`, `pytest-timeout`). The full test suite is **1,764+ tests** and runs in roughly 100 seconds locally.

## Workflow

We use a worktree-per-issue pattern. For an issue numbered `N`:

```bash
git worktree add ../gh-link-auditor-N -b N-short-description
cd ../gh-link-auditor-N
```

Then:

1. **LLD first.** Write the design in `docs/lld/active/LLD-N.md` before any code.
2. **Tests first.** Add failing tests that capture the spec (RED).
3. **Implement.** Make the tests pass (GREEN).
4. **Lint + format.** `poetry run ruff check . && poetry run ruff format .`
5. **Reports.** Create `docs/reports/active/1N-implementation-report.md` and `docs/reports/active/1N-test-report.md` before opening the PR.
6. **Commit + PR.** Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`). PR title and body must both include `Closes #N`.

`pr-sentinel` blocks the merge gate if the PR body is missing the `Closes #N` reference. CI runs the `Test` and `Lint` workflows on every PR and `Cerberus-AZ` auto-approves once they pass.

## Standards

- **Python 3.10+**, type hints required on new code.
- **Poetry** for all package management — never `pip install`. Always invoke Python via `poetry run python …`, never bare `python`.
- **Ruff** for lint and format (`select = ["E", "F", "W", "I"]`, line length 120). The Lint workflow blocks merges on failure.
- **≥95% test coverage** on changed lines. No exceptions. Run `poetry run pytest --cov=src --cov-report=term-missing` before pushing.
- **No `MagicMock`** in the suite — use the shared fakes in `tests/fakes/` (`FakeHTTPResponse`, `FakeGitHubClient`, `FakeArchiveClient`, `FakeGitHubContentsClient`).
- **Mock DNS** in tests that follow redirects — SSRF validation calls real DNS otherwise.

## Reporting issues

Use the [GitHub Issues tab](https://github.com/martymcenroe/gh-link-auditor/issues). All code in this repo references an open issue — if you find a bug or want a feature, file an issue first.
