"""Recordable fake for the candidate-analysis GitHub facade (#403).

Project rule: NO MagicMock. The facade is the mockable boundary — tests
substitute this whole object rather than patching individual httpx calls.
Same pattern as ``tests/fakes/subagent.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gh_link_auditor.candidate_analysis import GitHubUnavailable


@dataclass
class FakeGitHubFacade:
    """Canned facade responses + a call log."""

    metadata: dict[str, Any] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    existing_paths: set[str] = field(default_factory=set)
    merged: list[dict[str, Any]] = field(default_factory=list)
    open: list[dict[str, Any]] = field(default_factory=list)

    # When set, the named method raises GitHubUnavailable.
    fail_on: str | None = None

    calls: list[str] = field(default_factory=list)

    def _check(self, method: str) -> None:
        self.calls.append(method)
        if self.fail_on == method:
            raise GitHubUnavailable(f"fake failure in {method}")

    def repo_metadata(self, owner: str, repo: str) -> dict[str, Any]:
        self._check("repo_metadata")
        return dict(self.metadata)

    def file_content(self, owner: str, repo: str, path: str) -> str:
        self._check("file_content")
        if path not in self.files:
            raise GitHubUnavailable(f"fake has no content for {path}")
        return self.files[path]

    def path_exists(self, owner: str, repo: str, path: str) -> bool:
        self._check("path_exists")
        return path in self.existing_paths

    def merged_prs(self, owner: str, repo: str, limit: int) -> list[dict[str, Any]]:
        self._check("merged_prs")
        return list(self.merged[:limit])

    def open_prs(self, owner: str, repo: str, limit: int) -> list[dict[str, Any]]:
        self._check("open_prs")
        return list(self.open[:limit])
