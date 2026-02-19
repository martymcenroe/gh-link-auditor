"""Tests for cleanup operations.

Covers LLD-019 scenarios:
- T140: Disk over limit (REQ-8)
- T150: Disk under limit (REQ-8)
- T160: Cleanup clone (REQ-9)
- T170: Cleanup remote branch (REQ-9)
- T270: Stale fork pruning (REQ-9)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from gh_link_auditor.batch.cleanup import (
    check_disk_usage,
    cleanup_clone,
    cleanup_remote_branch,
    prune_stale_forks,
)


class TestDiskUsage:
    """T140, T150: Disk usage checks (REQ-8)."""

    def test_over_limit(self, tmp_path) -> None:
        """T140: Disk over limit returns True."""
        # Create files totaling > threshold
        big_file = tmp_path / "large.bin"
        big_file.write_bytes(b"x" * (1024 * 1024))  # 1 MB

        usage, over = check_disk_usage(tmp_path, max_gb=0.0001)
        assert over is True
        assert usage > 0

    def test_under_limit(self, tmp_path) -> None:
        """T150: Disk under limit returns False."""
        small_file = tmp_path / "small.txt"
        small_file.write_text("hello")

        usage, over = check_disk_usage(tmp_path, max_gb=10.0)
        assert over is False

    def test_nonexistent_dir(self, tmp_path) -> None:
        usage, over = check_disk_usage(tmp_path / "nonexistent", max_gb=10.0)
        assert usage == 0.0
        assert over is False

    def test_empty_dir(self, tmp_path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        usage, over = check_disk_usage(empty, max_gb=10.0)
        assert usage == 0.0
        assert over is False


class TestCleanupClone:
    """T160: Cleanup deletes clone directory (REQ-9)."""

    def test_deletes_directory(self, tmp_path) -> None:
        clone_dir = tmp_path / "repo_clone"
        clone_dir.mkdir()
        (clone_dir / "file.txt").write_text("content")
        (clone_dir / "subdir").mkdir()
        (clone_dir / "subdir" / "nested.txt").write_text("nested")

        asyncio.run(cleanup_clone(clone_dir))

        assert not clone_dir.exists()

    def test_nonexistent_no_error(self, tmp_path) -> None:
        asyncio.run(cleanup_clone(tmp_path / "nonexistent"))


class TestCleanupRemoteBranch:
    """T170: Cleanup remote branch via API (REQ-9)."""

    def test_deletes_branch(self) -> None:
        """API called with correct params."""
        mock_resp = AsyncMock()
        mock_resp.status_code = 204

        with patch("gh_link_auditor.batch.cleanup.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.delete = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = asyncio.run(
                cleanup_remote_branch("owner/repo", "fix/branch", "ghp_token")
            )

        assert result is True
        mock_client.delete.assert_called_once()
        call_url = mock_client.delete.call_args[0][0]
        assert "owner/repo" in call_url
        assert "fix/branch" in call_url

    def test_failure_returns_false(self) -> None:
        mock_resp = AsyncMock()
        mock_resp.status_code = 404

        with patch("gh_link_auditor.batch.cleanup.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.delete = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = asyncio.run(
                cleanup_remote_branch("owner/repo", "fix/branch", "ghp_token")
            )

        assert result is False


class TestCleanupRemoteBranchError:
    """Tests for cleanup_remote_branch error handling."""

    def test_http_error_returns_false(self) -> None:
        import httpx

        with patch("gh_link_auditor.batch.cleanup.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.delete = AsyncMock(side_effect=httpx.ConnectError("network"))
            mock_client_cls.return_value = mock_client

            result = asyncio.run(
                cleanup_remote_branch("owner/repo", "branch", "token")
            )

        assert result is False


class TestPruneStaleForks:
    """T270: Stale fork pruning (REQ-9)."""

    def test_identifies_stale_forks(self) -> None:
        """Identifies merged-old and rejected-old, excludes open-recent."""
        forks = [
            {
                "full_name": "bot/merged-old",
                "created_at": "2025-01-01T00:00:00+00:00",
                "pr_status": "merged",
            },
            {
                "full_name": "bot/open-recent",
                "created_at": "2026-02-01T00:00:00+00:00",
                "pr_status": "open",
            },
            {
                "full_name": "bot/rejected-old",
                "created_at": "2025-06-01T00:00:00+00:00",
                "pr_status": "rejected",
            },
        ]

        stale = asyncio.run(prune_stale_forks(forks, "token", max_age_days=90))

        assert "bot/merged-old" in stale
        assert "bot/rejected-old" in stale
        assert "bot/open-recent" not in stale
        assert len(stale) == 2

    def test_empty_forks_list(self) -> None:
        stale = asyncio.run(prune_stale_forks([], "token"))
        assert stale == []

    def test_all_open_no_pruning(self) -> None:
        forks = [
            {
                "full_name": "bot/active",
                "created_at": "2025-01-01T00:00:00+00:00",
                "pr_status": "open",
            },
        ]
        stale = asyncio.run(prune_stale_forks(forks, "token"))
        assert stale == []
