"""Tests for metrics CLI subcommands.

Covers: metrics scan-history (no-db, empty-db, with-data, json format).
"""

from __future__ import annotations

import argparse
import json

from gh_link_auditor.cli.metrics_cmd import cmd_metrics_scan_history
from gh_link_auditor.unified_db import UnifiedDatabase


class TestScanHistoryCommand:
    def test_scan_history_no_db(self, tmp_path, capsys):
        """Returns 1 when DB doesn't exist."""
        args = argparse.Namespace(
            db_path=str(tmp_path / "nonexistent.db"),
            limit=20,
            format="text",
        )
        result = cmd_metrics_scan_history(args)
        assert result == 1
        assert "No database found" in capsys.readouterr().out

    def test_scan_history_empty_db(self, tmp_path, capsys):
        """Shows 'No scan history' for empty DB."""
        db_path = tmp_path / "test.db"
        udb = UnifiedDatabase(db_path)
        udb.close()

        args = argparse.Namespace(
            db_path=str(db_path),
            limit=20,
            format="text",
        )
        result = cmd_metrics_scan_history(args)
        assert result == 0
        assert "No scan history found" in capsys.readouterr().out

    def test_scan_history_with_data(self, tmp_path, capsys):
        """Shows scan data when available."""
        db_path = tmp_path / "test.db"
        udb = UnifiedDatabase(db_path)
        repo_id = udb.upsert_repo("owner/repo")
        scan_id = udb.record_scan(repo_id, "run-123")
        udb.complete_scan(
            scan_id,
            dead_links_found=5,
            fixes_generated=3,
            pr_submitted=1,
            decision="approved",
        )
        udb.close()

        args = argparse.Namespace(
            db_path=str(db_path),
            limit=20,
            format="text",
        )
        result = cmd_metrics_scan_history(args)
        assert result == 0
        output = capsys.readouterr().out
        assert "owner/repo" in output
        assert "approved" in output

    def test_scan_history_json_format(self, tmp_path, capsys):
        """JSON format outputs valid JSON."""
        db_path = tmp_path / "test.db"
        udb = UnifiedDatabase(db_path)
        repo_id = udb.upsert_repo("owner/repo")
        scan_id = udb.record_scan(repo_id, "run-456")
        udb.complete_scan(scan_id, dead_links_found=2)
        udb.close()

        args = argparse.Namespace(
            db_path=str(db_path),
            limit=20,
            format="json",
        )
        result = cmd_metrics_scan_history(args)
        assert result == 0
        output = capsys.readouterr().out
        data = json.loads(output)
        assert len(data) == 1
        assert data[0]["repo_full_name"] == "owner/repo"
        assert data[0]["dead_links_found"] == 2

    def test_scan_history_empty_json(self, tmp_path, capsys):
        """JSON format with no scans still returns 0."""
        db_path = tmp_path / "test.db"
        udb = UnifiedDatabase(db_path)
        udb.close()

        args = argparse.Namespace(
            db_path=str(db_path),
            limit=20,
            format="json",
        )
        result = cmd_metrics_scan_history(args)
        assert result == 0

    def test_scan_history_respects_limit(self, tmp_path, capsys):
        """--limit caps the number of results shown."""
        db_path = tmp_path / "test.db"
        udb = UnifiedDatabase(db_path)
        repo_id = udb.upsert_repo("owner/repo")
        for i in range(5):
            scan_id = udb.record_scan(repo_id, f"run-{i}")
            udb.complete_scan(scan_id)
        udb.close()

        args = argparse.Namespace(
            db_path=str(db_path),
            limit=2,
            format="json",
        )
        result = cmd_metrics_scan_history(args)
        assert result == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 2
