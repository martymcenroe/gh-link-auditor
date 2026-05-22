"""Tests for the bulk-scan CLI subcommand (#218)."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

from gh_link_auditor.bulk_scan import storage
from gh_link_auditor.cli.bulk_scan_cmd import (
    _cmd_list_runs,
    _cmd_report,
    _cmd_start,
    _cmd_status,
    _cmd_stop,
    _suggest_run_ids,
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


class TestCmdStartRunIdGate:
    """#231 — reject unknown --run-id unless --new-run is set."""

    def _args(self, **kw) -> argparse.Namespace:
        defaults = dict(target=10, run_id=None, db_path="", token=None, new_run=False)
        defaults.update(kw)
        return argparse.Namespace(**defaults)

    def test_unknown_run_id_rejects_without_new_run(self, tmp_path, capsys) -> None:
        db_path = str(tmp_path / "x.db")
        with UnifiedDatabase(db_path):
            pass  # init schema, no runs
        rc = _cmd_start(self._args(db_path=db_path, run_id="bulk-20260514T999999"))
        err = capsys.readouterr().err
        assert rc == 2
        assert "not found" in err
        assert "--new-run" in err

    def test_unknown_run_id_with_new_run_proceeds(self, tmp_path, capsys) -> None:
        """--new-run on unknown id is allowed; verify the runner gets called."""
        db_path = str(tmp_path / "x.db")
        with UnifiedDatabase(db_path):
            pass
        with patch("gh_link_auditor.bulk_scan.runner.run_full", return_value={"status": "done"}) as p:
            rc = _cmd_start(self._args(db_path=db_path, run_id="bulk-newid", new_run=True))
            assert p.call_count == 1
            assert p.call_args.args[1] == "bulk-newid"
        assert rc == 0

    def test_existing_run_id_resumes_without_new_run(self, tmp_path) -> None:
        db_path = str(tmp_path / "x.db")
        with UnifiedDatabase(db_path) as db:
            storage.create_run(db, "bulk-existing", 5, {})
        with patch("gh_link_auditor.bulk_scan.runner.run_full", return_value={"status": "done"}) as p:
            rc = _cmd_start(self._args(db_path=db_path, run_id="bulk-existing"))
            assert p.call_count == 1
        assert rc == 0

    def test_existing_run_id_with_new_run_rejected(self, tmp_path, capsys) -> None:
        """Inverse foot-gun: --new-run on an existing id is an error to avoid clobbering."""
        db_path = str(tmp_path / "x.db")
        with UnifiedDatabase(db_path) as db:
            storage.create_run(db, "bulk-existing", 5, {})
        rc = _cmd_start(self._args(db_path=db_path, run_id="bulk-existing", new_run=True))
        err = capsys.readouterr().err
        assert rc == 2
        assert "already exists" in err
        assert "Drop --new-run" in err

    def test_no_run_id_autogenerates(self, tmp_path) -> None:
        """Without --run-id, behavior unchanged: auto-generate id, create run, fire."""
        db_path = str(tmp_path / "x.db")
        with UnifiedDatabase(db_path):
            pass
        with patch("gh_link_auditor.bulk_scan.runner.run_full", return_value={"status": "done"}) as p:
            rc = _cmd_start(self._args(db_path=db_path, run_id=None))
            assert p.call_count == 1
            # Auto-generated id starts with bulk-
            assert p.call_args.args[1].startswith("bulk-")
        assert rc == 0

    def test_suggestion_surfaces_close_match(self, tmp_path, capsys) -> None:
        """Did-you-mean lists prefix-matched existing run_ids on unknown-id error."""
        db_path = str(tmp_path / "x.db")
        with UnifiedDatabase(db_path) as db:
            storage.create_run(db, "bulk-20260514T042627Z", 5, {})
            storage.create_run(db, "bulk-20260514T030834Z", 5, {})
        rc = _cmd_start(self._args(db_path=db_path, run_id="bulk-20260514T042627"))
        err = capsys.readouterr().err
        assert rc == 2
        assert "Did you mean" in err
        # The Z-suffix sibling should be suggested (longest common prefix)
        assert "bulk-20260514T042627Z" in err


class TestSuggestRunIds:
    def test_longest_prefix_first(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "bulk-20260514T042627Z", 1, {})
            storage.create_run(db, "bulk-20260514T030834Z", 1, {})
            storage.create_run(db, "bulk-20260514T021236Z", 1, {})
            out = _suggest_run_ids(db, "bulk-20260514T042627")
        # Z-sibling has the longest prefix match → ranks first
        assert out[0] == "bulk-20260514T042627Z"

    def test_no_overlap_returns_empty(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "alpha", 1, {})
            out = _suggest_run_ids(db, "totally-different")
        assert out == []

    def test_empty_db_returns_empty(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            out = _suggest_run_ids(db, "anything")
        assert out == []

    def test_respects_max_suggest(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            for i in range(10):
                storage.create_run(db, f"bulk-prefix-match-{i}", 1, {})
            out = _suggest_run_ids(db, "bulk-prefix-match", max_suggest=3)
        assert len(out) == 3
