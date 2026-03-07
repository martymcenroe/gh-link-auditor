"""Tests for CLI main and run subcommand.

See LLD #22 §10.0: CLI entry point tests.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from gh_link_auditor.cli.main import build_parser, main
from gh_link_auditor.cli.run import cmd_run


class TestBuildParser:
    """Tests for build_parser()."""

    def test_returns_parser(self) -> None:
        parser = build_parser()
        assert parser is not None

    def test_has_run_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "https://github.com/org/repo"])
        assert args.command == "run"
        assert args.target == "https://github.com/org/repo"

    def test_run_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "t"])
        assert args.max_links == 50
        assert args.max_cost == 5.00
        assert args.confidence == 0.8
        assert args.dry_run is False
        assert args.verbose is False

    def test_run_custom_options(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run",
                "t",
                "--max-links",
                "100",
                "--max-cost",
                "10.0",
                "--confidence",
                "0.9",
                "--dry-run",
                "--verbose",
            ]
        )
        assert args.max_links == 100
        assert args.max_cost == 10.0
        assert args.confidence == 0.9
        assert args.dry_run is True
        assert args.verbose is True


class TestMain:
    """Tests for main() entry point."""

    def test_no_command_shows_help(self, capsys) -> None:
        result = main([])
        assert result == 0

    def test_run_command_calls_pipeline(self, tmp_path: Path) -> None:
        mock_result = {
            "dead_links": [],
            "fixes": [],
            "scan_complete": True,
            "circuit_breaker_triggered": False,
            "cost_limit_reached": False,
            "errors": [],
        }
        with patch(
            "gh_link_auditor.cli.run.run_pipeline",
            return_value=mock_result,
        ):
            result = main(["run", str(tmp_path)])
        assert result == 0


class TestCmdRun:
    """Tests for cmd_run()."""

    def test_clean_repo_returns_0(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", str(tmp_path)])
        mock_result = {
            "dead_links": [],
            "fixes": [],
            "scan_complete": True,
            "circuit_breaker_triggered": False,
            "cost_limit_reached": False,
            "errors": [],
        }
        with patch(
            "gh_link_auditor.cli.run.run_pipeline",
            return_value=mock_result,
        ):
            result = cmd_run(args)
        assert result == 0

    def test_circuit_breaker_returns_2(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", str(tmp_path)])
        mock_result = {
            "dead_links": [{"url": f"https://dead{i}.com"} for i in range(100)],
            "fixes": [],
            "circuit_breaker_triggered": True,
            "cost_limit_reached": False,
            "errors": [],
        }
        with patch(
            "gh_link_auditor.cli.run.run_pipeline",
            return_value=mock_result,
        ):
            result = cmd_run(args)
        assert result == 2

    def test_cost_limit_returns_3(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", str(tmp_path)])
        mock_result = {
            "dead_links": [{"url": "https://dead.com"}],
            "fixes": [],
            "circuit_breaker_triggered": False,
            "cost_limit_reached": True,
            "errors": [],
        }
        with patch(
            "gh_link_auditor.cli.run.run_pipeline",
            return_value=mock_result,
        ):
            result = cmd_run(args)
        assert result == 3

    def test_errors_returns_1(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", str(tmp_path)])
        mock_result = {
            "dead_links": [],
            "fixes": [],
            "circuit_breaker_triggered": False,
            "cost_limit_reached": False,
            "errors": ["Something went wrong"],
        }
        with patch(
            "gh_link_auditor.cli.run.run_pipeline",
            return_value=mock_result,
        ):
            result = cmd_run(args)
        assert result == 1

    def test_pipeline_exception_returns_1(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", str(tmp_path)])
        with patch(
            "gh_link_auditor.cli.run.run_pipeline",
            side_effect=Exception("boom"),
        ):
            result = cmd_run(args)
        assert result == 1

    def test_with_dead_links_and_fixes(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", str(tmp_path)])
        mock_result = {
            "dead_links": [{"url": "https://dead.com"}],
            "fixes": [{"source_file": "a.md", "unified_diff": "diff"}],
            "circuit_breaker_triggered": False,
            "cost_limit_reached": False,
            "errors": [],
        }
        with patch(
            "gh_link_auditor.cli.run.run_pipeline",
            return_value=mock_result,
        ):
            result = cmd_run(args)
        assert result == 0

    def test_verbose_mode(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", str(tmp_path), "--verbose"])
        mock_result = {
            "dead_links": [],
            "fixes": [],
            "circuit_breaker_triggered": False,
            "cost_limit_reached": False,
            "errors": [],
        }
        with patch(
            "gh_link_auditor.cli.run.run_pipeline",
            return_value=mock_result,
        ):
            result = cmd_run(args)
        assert result == 0

    def test_llm_model_env_override(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("LLM_MODEL_NAME", "claude-3-haiku")
        parser = build_parser()
        args = parser.parse_args(["run", str(tmp_path), "--verbose"])
        mock_result = {
            "dead_links": [],
            "fixes": [],
            "circuit_breaker_triggered": False,
            "cost_limit_reached": False,
            "errors": [],
        }
        with patch(
            "gh_link_auditor.cli.run.run_pipeline",
            return_value=mock_result,
        ):
            result = cmd_run(args)
        assert result == 0
