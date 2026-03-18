"""Fake GitHub Contents API client for testing.

Replaces real HTTP calls with configurable in-memory responses.
"""

from __future__ import annotations


class FakeGitHubContentsClient:
    """Fake GitHubContentsClient with pre-configured responses.

    Configure file trees and content, then call the same methods
    as the real GitHubContentsClient.
    """

    def __init__(self) -> None:
        self._files: dict[str, dict[str, str]] = {}
        self.list_doc_files_calls: list[tuple[str, str]] = []
        self.fetch_file_content_calls: list[tuple[str, str, str]] = []

    def configure_repo_files(self, owner: str, repo: str, files: dict[str, str]) -> None:
        """Set file tree for a repo.

        Args:
            owner: Repository owner.
            repo: Repository name.
            files: Mapping of relative path -> file content.
        """
        self._files[f"{owner}/{repo}"] = files

    def list_doc_files(self, owner: str, repo: str) -> list[str]:
        """Return configured doc file paths (filtered by extension)."""
        self.list_doc_files_calls.append((owner, repo))
        key = f"{owner}/{repo}"
        all_files = self._files.get(key, {})
        doc_extensions = {".md", ".rst", ".txt", ".adoc"}
        doc_files = [
            path for path in all_files
            if any(path.lower().endswith(ext) for ext in doc_extensions)
        ]
        return sorted(doc_files)

    def fetch_file_content(self, owner: str, repo: str, path: str) -> str:
        """Return configured file content."""
        self.fetch_file_content_calls.append((owner, repo, path))
        key = f"{owner}/{repo}"
        repo_files = self._files.get(key, {})
        content = repo_files.get(path)
        if content is None:
            msg = f"File not found: {path} in {key}"
            raise FileNotFoundError(msg)
        return content
