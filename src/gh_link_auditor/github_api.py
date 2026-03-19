"""Minimal GitHub Contents API client for clone-last architecture.

Provides file listing and content fetching via the Contents API,
avoiding the need to clone repositories for N0/N1 scanning.

See LLD #67 for design specification.
"""

from __future__ import annotations

import base64
import logging

import httpx

logger = logging.getLogger(__name__)

_DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}

_BASE_URL = "https://api.github.com"


class GitHubContentsClient:
    """GitHub Contents API client for file listing and fetching.

    Uses GET /repos/{owner}/{repo}/contents/{path} for both
    directory listing (recursive) and file content retrieval.
    """

    def __init__(self, token: str | None = None) -> None:
        """Initialize client.

        Args:
            token: GitHub personal access token.
                   Falls back to GITHUB_TOKEN env var if not provided.
        """
        if token is not None:
            self._token = token
        else:
            from gh_link_auditor.auth import resolve_github_token

            self._token = resolve_github_token()
        headers: dict[str, str] = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "gh-link-auditor",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._client = httpx.Client(
            base_url=_BASE_URL,
            headers=headers,
            timeout=30.0,
        )

    def list_doc_files(self, owner: str, repo: str) -> list[str]:
        """Recursively list documentation files in a repository.

        Walks the repository tree via the Contents API, filtering
        for doc extensions (.md, .rst, .txt, .adoc).

        Args:
            owner: Repository owner (e.g., "anthropics").
            repo: Repository name (e.g., "claude-code").

        Returns:
            Sorted list of relative file paths.
        """
        doc_files: list[str] = []
        self._walk_directory(owner, repo, "", doc_files)
        return sorted(doc_files)

    def _walk_directory(
        self,
        owner: str,
        repo: str,
        path: str,
        doc_files: list[str],
    ) -> None:
        """Recursively walk a directory via Contents API.

        Args:
            owner: Repository owner.
            repo: Repository name.
            path: Directory path relative to repo root.
            doc_files: Accumulator list for discovered doc file paths.
        """
        url = f"/repos/{owner}/{repo}/contents/{path}"
        response = self._client.get(url)
        response.raise_for_status()
        items = response.json()

        if not isinstance(items, list):
            return

        for item in items:
            item_type = item.get("type", "")
            item_path = item.get("path", "")

            if item_type == "dir":
                self._walk_directory(owner, repo, item_path, doc_files)
            elif item_type == "file":
                if any(item_path.lower().endswith(ext) for ext in _DOC_EXTENSIONS):
                    doc_files.append(item_path)

    def fetch_file_content(self, owner: str, repo: str, path: str) -> str:
        """Fetch and decode file content from a repository.

        Uses the Contents API which returns base64-encoded content.

        Args:
            owner: Repository owner.
            repo: Repository name.
            path: File path relative to repo root.

        Returns:
            Decoded file content as string.

        Raises:
            httpx.HTTPStatusError: If the API request fails.
            FileNotFoundError: If the file does not exist.
        """
        url = f"/repos/{owner}/{repo}/contents/{path}"
        response = self._client.get(url)

        if response.status_code == 404:
            msg = f"File not found: {path} in {owner}/{repo}"
            raise FileNotFoundError(msg)

        response.raise_for_status()
        data = response.json()

        encoding = data.get("encoding", "")
        content = data.get("content", "")

        if encoding == "base64":
            return base64.b64decode(content).decode("utf-8", errors="replace")

        return content

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()
