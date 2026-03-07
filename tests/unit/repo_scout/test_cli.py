"""Tests for repo_scout.cli."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from repo_scout.cli import build_parser, main, print_progress, print_statistics
from repo_scout.models import DiscoverySource, make_repo_record


def _repo(owner: str = "org", name: str = "repo", source: str = "awesome_list") -> dict:
    src = DiscoverySource(source)
    return make_repo_record(owner=owner, name=name, source=src)


class TestBuildParser:
    """Tests for build_parser."""

    def test_default_values(self) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        assert args.awesome_lists == []
        assert args.root_users == []
        assert args.keywords == []
        assert args.star_depth == 2
        assert args.output == "targets.json"
        assert args.format == "json"
        assert args.seed_repos == []
        assert args.max_stargazers == 100
        assert args.max_repo_age_months == 6

    def test_awesome_lists(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--awesome-lists", "url1", "url2"])
        assert args.awesome_lists == ["url1", "url2"]

    def test_root_users(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--root-users", "user1"])
        assert args.root_users == ["user1"]

    def test_keywords(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--keywords", "python", "testing"])
        assert args.keywords == ["python", "testing"]

    def test_star_depth(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--star-depth", "5"])
        assert args.star_depth == 5

    def test_output_and_format(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--output", "out.txt", "--format", "txt"])
        assert args.output == "out.txt"
        assert args.format == "txt"

    def test_seed_repos(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--seed-repos", "anthropics/claude-code", "org/repo"])
        assert args.seed_repos == ["anthropics/claude-code", "org/repo"]

    def test_max_stargazers(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--max-stargazers", "50"])
        assert args.max_stargazers == 50

    def test_max_repo_age_months(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--max-repo-age-months", "12"])
        assert args.max_repo_age_months == 12


class TestPrintProgress:
    """Tests for print_progress."""

    def test_output_to_stderr(self, capsys: pytest.CaptureFixture) -> None:
        print_progress("Testing", 1, 5)
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "[1/5] Testing" in captured.err


class TestPrintStatistics:
    """Tests for print_statistics."""

    def test_basic_stats(self, capsys: pytest.CaptureFixture) -> None:
        repos = [
            _repo("org1", "a", "awesome_list"),
            _repo("org2", "b", "starred_repo"),
        ]
        print_statistics(repos)
        captured = capsys.readouterr()
        assert "Total unique repos: 2" in captured.err
        assert "awesome_list" in captured.err
        assert "starred_repo" in captured.err

    def test_empty_repos(self, capsys: pytest.CaptureFixture) -> None:
        print_statistics([])
        captured = capsys.readouterr()
        assert "Total unique repos: 0" in captured.err

    def test_multi_source_repo(self, capsys: pytest.CaptureFixture) -> None:
        repo = _repo("org", "repo", "awesome_list")
        repo["sources"] = ["awesome_list", "starred_repo"]
        print_statistics([repo])
        captured = capsys.readouterr()
        assert "awesome_list: 1" in captured.err
        assert "starred_repo: 1" in captured.err


class TestMain:
    """Tests for main CLI entry point."""

    @patch("repo_scout.cli.GitHubClient")
    @patch("repo_scout.cli.write_output")
    def test_no_sources_writes_empty(self, mock_write: MagicMock, mock_client_cls: MagicMock, tmp_path: Path) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_write.return_value = 0

        output = str(tmp_path / "out.json")
        exit_code = main(["--output", output])
        assert exit_code == 0
        mock_client.close.assert_called_once()

    @patch("repo_scout.cli.GitHubClient")
    @patch("repo_scout.cli.parse_awesome_list")
    @patch("repo_scout.cli.write_output")
    def test_awesome_list_source(
        self,
        mock_write: MagicMock,
        mock_parse: MagicMock,
        mock_client_cls: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_parse.return_value = [_repo("org", "repo")]
        mock_write.return_value = 1

        output = str(tmp_path / "out.json")
        exit_code = main(["--awesome-lists", "https://github.com/org/awesome", "--output", output])
        assert exit_code == 0
        mock_parse.assert_called_once_with("https://github.com/org/awesome")

    @patch("repo_scout.cli.GitHubClient")
    @patch("repo_scout.cli.walk_starred_repos")
    @patch("repo_scout.cli.write_output")
    def test_star_walking_source(
        self,
        mock_write: MagicMock,
        mock_walk: MagicMock,
        mock_client_cls: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_walk.return_value = [_repo("org", "starred", "starred_repo")]
        mock_write.return_value = 1

        output = str(tmp_path / "out.json")
        exit_code = main(["--root-users", "user1", "--star-depth", "3", "--output", output])
        assert exit_code == 0
        mock_walk.assert_called_once_with("user1", mock_client, max_depth=3)

    @patch("repo_scout.cli.GitHubClient")
    @patch("repo_scout.cli.suggest_repos")
    @patch("repo_scout.cli.write_output")
    def test_keywords_source(
        self,
        mock_write: MagicMock,
        mock_suggest: MagicMock,
        mock_client_cls: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_suggest.return_value = []
        mock_write.return_value = 0

        output = str(tmp_path / "out.json")
        exit_code = main(["--keywords", "python", "--output", output])
        assert exit_code == 0
        mock_suggest.assert_called_once()

    @patch("repo_scout.cli.GitHubClient")
    @patch("repo_scout.cli.parse_awesome_list")
    def test_error_returns_1(self, mock_parse: MagicMock, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_parse.side_effect = RuntimeError("Boom")

        exit_code = main(["--awesome-lists", "https://example.com"])
        assert exit_code == 1
        mock_client.close.assert_called_once()

    @patch("repo_scout.cli.harvest_from_stargazers")
    @patch("repo_scout.cli.GitHubClient")
    @patch("repo_scout.cli.write_output")
    def test_seed_repos_calls_harvester(
        self,
        mock_write: MagicMock,
        mock_client_cls: MagicMock,
        mock_harvest: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_harvest.return_value = [_repo("alice", "tool", "stargazer_target")]
        mock_write.return_value = 1

        output = str(tmp_path / "out.json")
        exit_code = main(
            [
                "--seed-repos",
                "anthropics/claude-code",
                "--max-stargazers",
                "50",
                "--max-repo-age-months",
                "3",
                "--output",
                output,
            ]
        )
        assert exit_code == 0
        mock_harvest.assert_called_once()
        call_kwargs = mock_harvest.call_args
        assert call_kwargs[1]["seed_repos"] == ["anthropics/claude-code"]
        assert call_kwargs[1]["max_stargazers"] == 50
        assert call_kwargs[1]["max_repo_age_months"] == 3

    @patch("repo_scout.cli.GitHubClient")
    @patch("repo_scout.cli.write_output")
    @patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test"})
    def test_reads_github_token_from_env(
        self, mock_write: MagicMock, mock_client_cls: MagicMock, tmp_path: Path
    ) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_write.return_value = 0

        output = str(tmp_path / "out.json")
        main(["--output", output])
        mock_client_cls.assert_called_once_with(token="ghp_test")
