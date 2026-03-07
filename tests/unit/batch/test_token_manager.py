"""Tests for token management and rotation.

Covers LLD-019 scenarios:
- T090: Token rotation picks highest remaining (REQ-5)
- T100: Insufficient token scopes (REQ-6)
- T110: All tokens exhausted (REQ-5)
- T120: Token invalidation on 401 (REQ-5)
- T260: Token file permission check (REQ-6)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from gh_link_auditor.batch.exceptions import (
    AllTokensExhaustedError,
    InsufficientScopesError,
)
from gh_link_auditor.batch.token_manager import (
    TokenManager,
    check_token_file_permissions,
    load_tokens_from_env,
    load_tokens_from_file,
)


class TestTokenRotation:
    """T090: Token rotation picks highest remaining (REQ-5)."""

    def test_picks_highest_remaining(self) -> None:
        tm = TokenManager(["token_a", "token_b", "token_c"])
        # Manually set remaining values
        tm._states[0].remaining = 100
        tm._states[1].remaining = 500
        tm._states[2].remaining = 200

        best = tm.get_best_token()
        assert best.token == "token_b"
        assert best.remaining == 500

    def test_single_token(self) -> None:
        tm = TokenManager(["only_token"])
        tm._states[0].remaining = 1000
        best = tm.get_best_token()
        assert best.token == "only_token"


class TestAllTokensExhausted:
    """T110: All tokens exhausted (REQ-5)."""

    def test_all_invalid_raises(self) -> None:
        tm = TokenManager(["a", "b"])
        tm._states[0].is_valid = False
        tm._states[1].is_valid = False

        with pytest.raises(AllTokensExhaustedError) as exc_info:
            tm.get_best_token()
        assert exc_info.value.wait_time >= 0.0

    def test_all_remaining_zero_raises(self) -> None:
        tm = TokenManager(["a", "b"])
        future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        for ts in tm._states:
            ts.remaining = 0
            ts.reset_at = future

        with pytest.raises(AllTokensExhaustedError) as exc_info:
            tm.get_best_token()
        assert exc_info.value.wait_time > 0


class TestTokenInvalidation:
    """T120: Token invalidation on 401 (REQ-5)."""

    def test_invalidate_excludes_from_rotation(self) -> None:
        tm = TokenManager(["good", "bad"])
        tm._states[0].remaining = 100
        tm._states[1].remaining = 500

        tm.invalidate_token("bad")

        best = tm.get_best_token()
        assert best.token == "good"

    def test_invalidate_nonexistent_no_error(self) -> None:
        tm = TokenManager(["a"])
        tm.invalidate_token("nonexistent")  # Should not raise


class TestUpdateTokenState:
    """Tests for update_token_state from headers."""

    def test_updates_remaining_and_reset(self) -> None:
        tm = TokenManager(["mytoken"])
        tm.update_token_state(
            "mytoken",
            {
                "X-RateLimit-Remaining": "42",
                "X-RateLimit-Reset": "1700000000",
            },
        )
        assert tm._states[0].remaining == 42
        assert tm._states[0].reset_at is not None


class TestTokenFilePermissions:
    """T260: Token file permission check (REQ-6)."""

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix permissions only")
    def test_warns_on_world_readable(self, tmp_path, caplog) -> None:
        token_file = tmp_path / "tokens.txt"
        token_file.write_text("ghp_test123\n")
        os.chmod(str(token_file), 0o644)

        with caplog.at_level(logging.WARNING):
            check_token_file_permissions(token_file)

        assert "permissive" in caplog.text.lower() or "permission" in caplog.text.lower()

    def test_no_crash_on_missing_file(self, tmp_path) -> None:
        check_token_file_permissions(tmp_path / "nonexistent")  # Should not raise

    def test_windows_permission_check(self, tmp_path) -> None:
        """On Windows, permission bits may differ; ensure no crash."""
        token_file = tmp_path / "tokens.txt"
        token_file.write_text("ghp_test\n")
        check_token_file_permissions(token_file)  # Should not raise


class TestLoadTokensFromFile:
    """Tests for loading tokens from file."""

    def test_loads_multiple_tokens(self, tmp_path) -> None:
        token_file = tmp_path / "tokens.txt"
        token_file.write_text("ghp_token1\nghp_token2\n\nghp_token3\n")
        tokens = load_tokens_from_file(token_file)
        assert tokens == ["ghp_token1", "ghp_token2", "ghp_token3"]

    def test_strips_whitespace(self, tmp_path) -> None:
        token_file = tmp_path / "tokens.txt"
        token_file.write_text("  ghp_token1  \n")
        tokens = load_tokens_from_file(token_file)
        assert tokens == ["ghp_token1"]


class TestValidateAll:
    """T100: Insufficient token scopes (REQ-6)."""

    def test_insufficient_scopes_raises(self) -> None:
        """Token with wrong scopes raises InsufficientScopesError."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {
            "X-OAuth-Scopes": "read:user",
            "X-RateLimit-Remaining": "5000",
            "X-RateLimit-Reset": "1700000000",
        }

        async def mock_get(*args, **kwargs):
            return mock_resp

        with patch("gh_link_auditor.batch.token_manager.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client

            tm = TokenManager(["ghp_testtoken1234"])
            with pytest.raises(InsufficientScopesError) as exc_info:
                asyncio.run(tm.validate_all())

            assert "public_repo" in exc_info.value.missing or "repo" in exc_info.value.missing

    def test_valid_scopes_pass(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {
            "X-OAuth-Scopes": "repo, public_repo, read:user",
            "X-RateLimit-Remaining": "4500",
            "X-RateLimit-Reset": "1700000000",
        }

        with patch("gh_link_auditor.batch.token_manager.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client

            tm = TokenManager(["ghp_goodtoken"])
            states = asyncio.run(tm.validate_all())

            assert states[0].remaining == 4500
            assert states[0].is_valid is True

    def test_401_invalidates_token(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.headers = {}

        with patch("gh_link_auditor.batch.token_manager.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client

            tm = TokenManager(["ghp_badtoken"])
            states = asyncio.run(tm.validate_all())

            assert states[0].is_valid is False

    def test_http_error_invalidates_token(self) -> None:
        with patch("gh_link_auditor.batch.token_manager.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("network"))
            mock_cls.return_value = mock_client

            tm = TokenManager(["ghp_errortoken"])
            states = asyncio.run(tm.validate_all())

            assert states[0].is_valid is False


class TestLoadTokensFromEnv:
    """Tests for loading tokens from environment."""

    def test_loads_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_envtoken")
        tokens = load_tokens_from_env()
        assert tokens == ["ghp_envtoken"]

    def test_empty_when_not_set(self, monkeypatch) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        tokens = load_tokens_from_env()
        assert tokens == []
