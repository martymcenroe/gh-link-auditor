"""Tests that every default-path site resolves to the same canonical DB.

See LLD-176 for the why. Before #176, three different defaults caused
`ghla metrics campaign` to read a DB the pipeline never wrote to.
"""

from __future__ import annotations

import argparse
import inspect

from gh_link_auditor.cli import blacklist_cmd, metrics_cmd, recheck_cmd
from gh_link_auditor.pipeline.state import create_initial_state
from gh_link_auditor.state_db import StateDatabase
from gh_link_auditor.unified_db import DEFAULT_DB_PATH


class TestPipelineStateDefault:
    """`create_initial_state(db_path=None)` resolves to the canonical default."""

    def test_db_path_none_resolves_to_canonical(self) -> None:
        state = create_initial_state(target="x", db_path=None)
        assert state["db_path"] == str(DEFAULT_DB_PATH)

    def test_explicit_db_path_overrides(self, tmp_path) -> None:
        explicit = tmp_path / "custom.db"
        state = create_initial_state(target="x", db_path=str(explicit))
        assert state["db_path"] == str(explicit)


class TestMetricsCmdDefault:
    """`metrics` subcommand argparse defaults match the canonical."""

    def _make_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        metrics_cmd.build_metrics_parser(sub)
        return parser

    def test_campaign_db_path_default(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args(["metrics", "campaign"])
        assert args.db_path == str(DEFAULT_DB_PATH)

    def test_refresh_db_path_default(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args(["metrics", "refresh"])
        assert args.db_path == str(DEFAULT_DB_PATH)

    def test_scan_history_db_path_default(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args(["metrics", "scan-history"])
        assert args.db_path == str(DEFAULT_DB_PATH)


class TestBlacklistCmdDefault:
    """`blacklist` subcommand argparse defaults match the canonical."""

    def _make_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        blacklist_cmd.build_blacklist_parser(sub)
        return parser

    def test_list_db_path_default(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args(["blacklist", "list"])
        assert args.db_path == str(DEFAULT_DB_PATH)


class TestRecheckCmdDefault:
    """`recheck` subcommand argparse defaults match the canonical."""

    def _make_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        recheck_cmd.build_recheck_parser(sub)
        return parser

    def test_db_path_default(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args(["recheck"])
        assert args.db_path == str(DEFAULT_DB_PATH)


class TestStateDatabaseDefault:
    """`StateDatabase()` constructor default matches the canonical."""

    def test_init_default_param(self) -> None:
        sig = inspect.signature(StateDatabase.__init__)
        default = sig.parameters["db_path"].default
        # Compare as str so a Path-vs-str mismatch doesn't false-positive.
        assert str(default) == str(DEFAULT_DB_PATH)


class TestPipelineMetricsRoundtrip:
    """End-to-end: write via one site, read via another, same default."""

    def test_pipeline_default_equals_metrics_default(self) -> None:
        """The pipeline's default db_path is the same file metrics reads."""
        pipeline_state = create_initial_state(target="x", db_path=None)
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        metrics_cmd.build_metrics_parser(sub)
        metrics_args = parser.parse_args(["metrics", "campaign"])
        assert pipeline_state["db_path"] == metrics_args.db_path
