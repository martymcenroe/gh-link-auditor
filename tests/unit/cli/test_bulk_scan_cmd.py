"""Tests for the bulk-scan CLI subcommand (#218)."""

from __future__ import annotations

import argparse
from pathlib import Path

from gh_link_auditor.bulk_scan import storage
from gh_link_auditor.cli.bulk_scan_cmd import (
    _cmd_list_runs,
    _cmd_report,
    _cmd_status,
    _cmd_stop,
    build_bulk_scan_parser,
)
from gh_link_auditor.unified_db import UnifiedDatabase


def _ns(**kw) -> argparse.Namespace:
    return argparse.Namespace(**kw)


class TestParserRegistration:
    def test_subparsers_registered(self) -> None:
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        build_bulk_scan_parser(sub)
        args = parser.parse_args(["bulk-scan", "list-runs"])
        assert args.command == "bulk-scan"
        assert args.bulk_scan_command == "list-runs"

    def test_start_defaults_target(self) -> None:
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        build_bulk_scan_parser(sub)
        args = parser.parse_args(["bulk-scan", "start"])
        assert args.target > 0  # default applied

    def test_report_requires_run_id(self) -> None:
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        build_bulk_scan_parser(sub)
        try:
            parser.parse_args(["bulk-scan", "report"])
            raise AssertionError("Should require --run-id")
        except SystemExit:
            pass


class TestCmdStatus:
    def test_no_runs(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "x.db")
        with UnifiedDatabase(db_path):
            pass
        rc = _cmd_status(_ns(db_path=db_path, run_id=None))
        out = capsys.readouterr().out
        assert rc == 0
        assert "no runs found" in out

    def test_existing_run(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "x.db")
        with UnifiedDatabase(db_path) as db:
            storage.create_run(db, "r1", 100, {})
        rc = _cmd_status(_ns(db_path=db_path, run_id="r1"))
        out = capsys.readouterr().out
        assert rc == 0
        assert "r1" in out
        assert "selecting" in out

    def test_missing_run_returns_1(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "x.db")
        with UnifiedDatabase(db_path):
            pass
        rc = _cmd_status(_ns(db_path=db_path, run_id="missing"))
        out = capsys.readouterr().out
        assert rc == 1
        assert "not found" in out


class TestCmdStop:
    def test_writes_abort_marker(self, tmp_path, capsys, monkeypatch) -> None:
        marker = tmp_path / "abort"
        monkeypatch.setattr("gh_link_auditor.cli.bulk_scan_cmd.ABORT_FILE", str(marker))
        rc = _cmd_stop(_ns())
        out = capsys.readouterr().out
        assert rc == 0
        assert "stop requested" in out
        assert Path(marker).exists()


class TestCmdReport:
    def test_writes_report(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "x.db")
        out_path = str(tmp_path / "report.md")
        with UnifiedDatabase(db_path) as db:
            storage.create_run(db, "r1", 1, {})
            storage.upsert_repo(db, "r1", "a/b")
            storage.add_finding(
                db,
                "r1",
                "a/b",
                "docs/x.md",
                1,
                "http://dead/",
                "https://new/",
                "url_mutation",
                1,
                0.9,
                True,
                0.95,
            )
            storage.mark_findings_surfaced(db, [1])
        rc = _cmd_report(_ns(db_path=db_path, run_id="r1", out=out_path))
        msg = capsys.readouterr().out
        assert rc == 0
        assert "report written" in msg
        assert Path(out_path).exists()
        body = Path(out_path).read_text(encoding="utf-8")
        assert "a/b" in body
        assert "https://new/" in body


class TestCmdListRuns:
    def test_no_runs(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "x.db")
        with UnifiedDatabase(db_path):
            pass
        rc = _cmd_list_runs(_ns(db_path=db_path))
        out = capsys.readouterr().out
        assert rc == 0
        assert "no runs" in out

    def test_lists_runs(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "x.db")
        with UnifiedDatabase(db_path) as db:
            storage.create_run(db, "r1", 1, {})
            storage.create_run(db, "r2", 2, {})
        rc = _cmd_list_runs(_ns(db_path=db_path))
        out = capsys.readouterr().out
        assert rc == 0
        assert "r1" in out
        assert "r2" in out
