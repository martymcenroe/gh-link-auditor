"""Tests for gh_link_auditor.auth — GitHub token resolution."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from gh_link_auditor.auth import resolve_github_token


class TestResolveGithubToken:
    """Tests for resolve_github_token()."""

    def test_returns_env_var_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_from_env")
        assert resolve_github_token() == "ghp_from_env"

    def test_env_var_takes_priority_over_cli(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_from_env")
        with patch("gh_link_auditor.auth.subprocess.run") as mock_run:
            token = resolve_github_token()
        mock_run.assert_not_called()
        assert token == "ghp_from_env"

    def test_falls_back_to_gh_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        completed = subprocess.CompletedProcess(
            args=["gh", "auth", "token"],
            returncode=0,
            stdout="ghp_from_cli\n",
            stderr="",
        )
        with patch("gh_link_auditor.auth.subprocess.run", return_value=completed):
            assert resolve_github_token() == "ghp_from_cli"

    def test_strips_whitespace_from_cli_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        completed = subprocess.CompletedProcess(
            args=["gh", "auth", "token"],
            returncode=0,
            stdout="  ghp_trimmed  \n",
            stderr="",
        )
        with patch("gh_link_auditor.auth.subprocess.run", return_value=completed):
            assert resolve_github_token() == "ghp_trimmed"

    def test_returns_empty_when_cli_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        completed = subprocess.CompletedProcess(
            args=["gh", "auth", "token"],
            returncode=1,
            stdout="",
            stderr="not logged in",
        )
        with patch("gh_link_auditor.auth.subprocess.run", return_value=completed):
            assert resolve_github_token() == ""

    def test_returns_empty_when_gh_not_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch(
            "gh_link_auditor.auth.subprocess.run", side_effect=FileNotFoundError
        ):
            assert resolve_github_token() == ""

    def test_returns_empty_on_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch(
            "gh_link_auditor.auth.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=5),
        ):
            assert resolve_github_token() == ""

    def test_returns_empty_string_not_none_when_no_sources(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        completed = subprocess.CompletedProcess(
            args=["gh", "auth", "token"],
            returncode=1,
            stdout="",
            stderr="",
        )
        with patch("gh_link_auditor.auth.subprocess.run", return_value=completed):
            result = resolve_github_token()
            assert result == ""
            assert isinstance(result, str)

    def test_passes_correct_args_to_subprocess(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        completed = subprocess.CompletedProcess(
            args=["gh", "auth", "token"],
            returncode=0,
            stdout="ghp_test\n",
            stderr="",
        )
        with patch("gh_link_auditor.auth.subprocess.run", return_value=completed) as mock_run:
            resolve_github_token()
            mock_run.assert_called_once_with(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=5,
            )

    def test_empty_env_var_triggers_cli_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "")
        completed = subprocess.CompletedProcess(
            args=["gh", "auth", "token"],
            returncode=0,
            stdout="ghp_fallback\n",
            stderr="",
        )
        with patch("gh_link_auditor.auth.subprocess.run", return_value=completed):
            assert resolve_github_token() == "ghp_fallback"
