"""Fake Git objects for testing.

Replaces MagicMock with typed fakes for git.Repo, git.cmd.Git, and git.IndexFile.
"""

from __future__ import annotations

from pathlib import Path


class FakeGitCmd:
    """Fake git.cmd.Git for testing git CLI operations."""

    def __init__(self) -> None:
        self.checkout_calls: list[tuple[tuple, dict]] = []
        self.push_calls: list[tuple[tuple, dict]] = []

    def checkout(self, *args: str, **kwargs: object) -> None:
        """Record checkout call."""
        self.checkout_calls.append((args, kwargs))

    def push(self, *args: str, **kwargs: object) -> None:
        """Record push call."""
        self.push_calls.append((args, kwargs))


class FakeIndex:
    """Fake git.IndexFile for testing staging/commit operations."""

    def __init__(self) -> None:
        self.added: list[list[str]] = []
        self.commit_messages: list[str] = []

    def add(self, items: list[str]) -> None:
        """Record staged items."""
        self.added.append(items)

    def commit(self, message: str) -> None:
        """Record commit."""
        self.commit_messages.append(message)


class FakeGitRepo:
    """Fake git.Repo for testing repository operations.

    Supports clone_from, git commands, and index operations.
    """

    _clone_calls: list[tuple[str, str | Path, dict]] = []

    def __init__(self, path: str | Path | None = None) -> None:
        self.working_dir = str(path) if path else "."
        self.git = FakeGitCmd()
        self.index = FakeIndex()

    @classmethod
    def clone_from(cls, url: str, to_path: str | Path, **kwargs: object) -> FakeGitRepo:
        """Simulate cloning a repository."""
        cls._clone_calls.append((url, to_path, kwargs))
        return cls(to_path)

    @classmethod
    def reset_clone_calls(cls) -> None:
        """Reset recorded clone calls between tests."""
        cls._clone_calls = []
