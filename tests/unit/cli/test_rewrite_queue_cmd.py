"""Tests for the `ghla rewrite-queue` CLI subcommands (#212)."""

from __future__ import annotations

import argparse

from gh_link_auditor.cli.rewrite_queue_cmd import (
    _cmd_clear,
    _cmd_export,
    _cmd_list,
    _cmd_mark_exported,
    _format_export_markdown,
    build_rewrite_queue_parser,
)
from gh_link_auditor.unified_db import UnifiedDatabase


def _seed(db_path: str, repo: str = "realpython/python-guide") -> None:
    with UnifiedDatabase(db_path) as db:
        db.add_to_rewrite_queue(
            dead_url="http://canopy.example.com/",
            source_file="docs/dev/env.rst",
            line_number=164,
            repo_full_name=repo,
            reason="discontinued 2018",
        )
        db.add_to_rewrite_queue(
            dead_url="http://komodo.example.com/",
            source_file="docs/dev/env.rst",
            line_number=177,
            repo_full_name=repo,
            reason="open-sourced 2023",
        )


def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


class TestCmdList:
    def test_empty_db(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "rq.db")
        with UnifiedDatabase(db_path):
            pass
        rc = _cmd_list(_ns(db_path=db_path, repo=None, all=False))
        out = capsys.readouterr().out
        assert rc == 0
        assert "No rewrite-queue entries" in out

    def test_empty_for_repo(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "rq.db")
        with UnifiedDatabase(db_path):
            pass
        rc = _cmd_list(_ns(db_path=db_path, repo="x/y", all=False))
        out = capsys.readouterr().out
        assert rc == 0
        assert "x/y" in out

    def test_lists_pending(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "rq.db")
        _seed(db_path)
        rc = _cmd_list(_ns(db_path=db_path, repo=None, all=False))
        out = capsys.readouterr().out
        assert rc == 0
        assert "canopy.example.com" in out
        assert "komodo.example.com" in out
        assert "pending" in out

    def test_filters_by_repo(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "rq.db")
        _seed(db_path, repo="a/b")
        _seed(db_path, repo="c/d")
        rc = _cmd_list(_ns(db_path=db_path, repo="a/b", all=False))
        out = capsys.readouterr().out
        assert rc == 0
        assert out.count("canopy") == 1  # only the a/b copy
        assert "c/d" not in out

    def test_all_includes_exported(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "rq.db")
        _seed(db_path)
        with UnifiedDatabase(db_path) as db:
            db.mark_rewrite_queue_exported("realpython/python-guide", 42)
        # Without --all: nothing shows
        _cmd_list(_ns(db_path=db_path, repo="realpython/python-guide", all=False))
        out = capsys.readouterr().out
        assert "No rewrite-queue entries" in out
        # With --all: entries visible, marked exported
        _cmd_list(_ns(db_path=db_path, repo="realpython/python-guide", all=True))
        out = capsys.readouterr().out
        assert "exported to issue #42" in out


class TestCmdExport:
    def test_no_pending(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "rq.db")
        with UnifiedDatabase(db_path):
            pass
        rc = _cmd_export(_ns(db_path=db_path, repo="x/y"))
        out = capsys.readouterr().out
        assert rc == 0
        assert "No pending entries" in out

    def test_prints_markdown_block(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "rq.db")
        _seed(db_path)
        rc = _cmd_export(_ns(db_path=db_path, repo="realpython/python-guide"))
        out = capsys.readouterr().out
        assert rc == 0
        assert "canopy.example.com" in out
        assert "komodo.example.com" in out
        assert "realpython/python-guide" in out

    def test_does_not_mark_exported(self, tmp_path) -> None:
        db_path = str(tmp_path / "rq.db")
        _seed(db_path)
        _cmd_export(_ns(db_path=db_path, repo="realpython/python-guide"))
        with UnifiedDatabase(db_path) as db:
            pending = db.get_rewrite_queue("realpython/python-guide")
            assert len(pending) == 2  # still pending


class TestCmdMarkExported:
    def test_marks_pending(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "rq.db")
        _seed(db_path)
        rc = _cmd_mark_exported(_ns(db_path=db_path, repo="realpython/python-guide", issue=42))
        out = capsys.readouterr().out
        assert rc == 0
        assert "marked 2 entries" in out
        assert "#42" in out
        with UnifiedDatabase(db_path) as db:
            assert db.get_rewrite_queue("realpython/python-guide") == []

    def test_singular_grammar(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "rq.db")
        with UnifiedDatabase(db_path) as db:
            db.add_to_rewrite_queue("u", "f", 1, "a/b")
        _cmd_mark_exported(_ns(db_path=db_path, repo="a/b", issue=1))
        out = capsys.readouterr().out
        assert "marked 1 entry" in out  # singular

    def test_zero_entries(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "rq.db")
        with UnifiedDatabase(db_path):
            pass
        rc = _cmd_mark_exported(_ns(db_path=db_path, repo="a/b", issue=1))
        out = capsys.readouterr().out
        assert rc == 0
        assert "marked 0 entries" in out


class TestCmdClear:
    def test_deletes_all_for_repo(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "rq.db")
        _seed(db_path)
        rc = _cmd_clear(_ns(db_path=db_path, repo="realpython/python-guide"))
        out = capsys.readouterr().out
        assert rc == 0
        assert "deleted 2 entries" in out
        with UnifiedDatabase(db_path) as db:
            assert db.get_rewrite_queue("realpython/python-guide", include_exported=True) == []

    def test_zero(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "rq.db")
        with UnifiedDatabase(db_path):
            pass
        rc = _cmd_clear(_ns(db_path=db_path, repo="x/y"))
        out = capsys.readouterr().out
        assert rc == 0
        assert "deleted 0 entries" in out


class TestFormatExportMarkdown:
    def test_casual_register(self, tmp_path) -> None:
        db_path = str(tmp_path / "rq.db")
        _seed(db_path)
        with UnifiedDatabase(db_path) as db:
            entries = db.get_rewrite_queue("realpython/python-guide")
        out = _format_export_markdown("realpython/python-guide", entries)
        # Draft-A house style: lowercase, no markdown headings, no bold
        assert "##" not in out
        assert "**" not in out
        assert out == out.replace("→", "")  # no unicode arrow
        assert "realpython/python-guide" in out
        assert "canopy.example.com" in out

    def test_includes_line_when_present(self, tmp_path) -> None:
        db_path = str(tmp_path / "rq.db")
        _seed(db_path)
        with UnifiedDatabase(db_path) as db:
            entries = db.get_rewrite_queue("realpython/python-guide")
        out = _format_export_markdown("realpython/python-guide", entries)
        assert "line 164" in out
        assert "line 177" in out

    def test_omits_line_when_none(self) -> None:
        entries = [
            {
                "id": 1,
                "dead_url": "u",
                "source_file": "f",
                "line_number": None,
                "repo_full_name": "o/r",
                "reason": "x",
                "added_at": "now",
                "exported_to_issue": None,
            }
        ]
        out = _format_export_markdown("o/r", entries)
        assert "line None" not in out
        assert "line" not in out  # no "line" word anywhere

    def test_default_reason_when_missing(self) -> None:
        entries = [
            {
                "id": 1,
                "dead_url": "u",
                "source_file": "f",
                "line_number": 1,
                "repo_full_name": "o/r",
                "reason": None,
                "added_at": "now",
                "exported_to_issue": None,
            }
        ]
        out = _format_export_markdown("o/r", entries)
        assert "needs rewrite" in out


class TestParserRegistration:
    def test_parser_registers(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        build_rewrite_queue_parser(subparsers)
        # Should not raise; parses --help
        args = parser.parse_args(["rewrite-queue", "list"])
        assert args.command == "rewrite-queue"
        assert args.rewrite_queue_command == "list"

    def test_export_requires_repo(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        build_rewrite_queue_parser(subparsers)
        try:
            parser.parse_args(["rewrite-queue", "export"])
            raise AssertionError("Should have errored on missing --repo")
        except SystemExit:
            pass  # expected

    def test_mark_exported_requires_repo_and_issue(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        build_rewrite_queue_parser(subparsers)
        try:
            parser.parse_args(["rewrite-queue", "mark-exported", "--repo", "x/y"])
            raise AssertionError("Should have errored on missing --issue")
        except SystemExit:
            pass
