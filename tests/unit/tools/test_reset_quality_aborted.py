"""Tests for tools/reset_quality_aborted.py.

The script is an operational recovery helper that mutates a local
SQLite DB. These tests exercise it against a tmp_path DB seeded with
the bulk_scan_runs / bulk_scan_findings / url_check_cache schema, so
the agent (or anyone else) can validate output and behavior without
touching the operator's real ghla.db.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent.parent / "tools" / "reset_quality_aborted.py"


def _load_script_module():
    """Import the script as a module so we can call main() directly."""
    spec = importlib.util.spec_from_file_location("reset_quality_aborted_under_test", _SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _init_schema(con: sqlite3.Connection) -> None:
    """Create the narrow schema the script reads/writes."""
    con.execute(
        """
        CREATE TABLE bulk_scan_runs (
            run_id TEXT PRIMARY KEY,
            status TEXT,
            quality_aborted INTEGER,
            completed_at TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE bulk_scan_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            dead_url TEXT NOT NULL,
            method TEXT NOT NULL DEFAULT 'pending',
            investigation_state TEXT NOT NULL DEFAULT 'pending',
            investigation_completed_at TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE url_check_cache (
            url TEXT PRIMARY KEY,
            http_status INTEGER
        )
        """
    )


def _seed_run(
    db_path: Path,
    *,
    run_id: str = "bulk-20260526T031148Z",
    status: str = "quality_aborted",
    quality_aborted: int = 1,
    completed_at: str | None = "2026-05-26T05:31:09.021709+00:00",
) -> None:
    """Create the schema + a run row."""
    con = sqlite3.connect(str(db_path))
    try:
        _init_schema(con)
        con.execute(
            "INSERT INTO bulk_scan_runs (run_id, status, quality_aborted, completed_at) VALUES (?, ?, ?, ?)",
            (run_id, status, quality_aborted, completed_at),
        )
        con.commit()
    finally:
        con.close()


def _add_finding(
    db_path: Path,
    *,
    run_id: str,
    dead_url: str,
    investigation_state: str,
    cache_http_status: int | None,
) -> None:
    """Add a Stage 1 placeholder finding plus its url_check_cache row."""
    con = sqlite3.connect(str(db_path))
    try:
        con.execute(
            "INSERT INTO bulk_scan_findings (run_id, dead_url, method, investigation_state) "
            "VALUES (?, ?, 'pending', ?)",
            (run_id, dead_url, investigation_state),
        )
        if cache_http_status is not None or True:  # always insert a cache row; status may be None
            con.execute(
                "INSERT OR REPLACE INTO url_check_cache (url, http_status) VALUES (?, ?)",
                (dead_url, cache_http_status),
            )
        con.commit()
    finally:
        con.close()


def _read_row(db_path: Path, run_id: str) -> dict | None:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT status, quality_aborted, completed_at FROM bulk_scan_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def _read_finding_state(db_path: Path, dead_url: str) -> str | None:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT investigation_state FROM bulk_scan_findings WHERE dead_url = ?",
            (dead_url,),
        ).fetchone()
        return row["investigation_state"] if row else None
    finally:
        con.close()


# --- dry-run ---------------------------------------------------------------


class TestDryRun:
    def test_does_not_mutate_db(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path)

        module = _load_script_module()
        rc = module.main(["--db-path", str(db_path), "--dry-run"])

        assert rc == 0
        row = _read_row(db_path, "bulk-20260526T031148Z")
        assert row is not None
        assert row["status"] == "quality_aborted"
        assert row["quality_aborted"] == 1

    def test_shows_projected_checking_state(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Regression for the 2026-05-26 bug: the projected post-reset
        state must be 'checking' (NOT 'investigating', which skips
        Stage 2). See #392 / audit lesson 2026-05-22."""
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path)

        module = _load_script_module()
        module.main(["--db-path", str(db_path), "--dry-run"])
        out = capsys.readouterr().out

        assert "BEFORE:" in out
        assert "AFTER (projected; not written):" in out
        after_block = out[out.index("AFTER (projected; not written):") :]
        assert "checking" in after_block
        # And the cautionary explanation against 'investigating' must
        # NOT appear in the AFTER block (only in BEFORE if a stale run
        # had it -- but our seed has 'quality_aborted', so it shouldn't
        # appear at all here).
        assert "Always reset to 'checking'" not in after_block

    def test_dry_run_does_not_recover_findings(self, tmp_path: Path) -> None:
        """Even with mis-stamped findings present, --dry-run must not
        flip them. The fix is computed; verifying happens after apply."""
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path)
        _add_finding(
            db_path,
            run_id="bulk-20260526T031148Z",
            dead_url="https://dead.example/x",
            investigation_state="skipped_alive",
            cache_http_status=404,
        )

        module = _load_script_module()
        module.main(["--db-path", str(db_path), "--dry-run"])

        # Finding still mis-stamped (no write happened).
        assert _read_finding_state(db_path, "https://dead.example/x") == "skipped_alive"


# --- apply -----------------------------------------------------------------


class TestApply:
    def test_sets_status_to_checking_not_investigating(self, tmp_path: Path) -> None:
        """The load-bearing regression: post-reset status must be
        'checking', never 'investigating'. The bug that broke the
        2026-05-26 scan was the script setting 'investigating'."""
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path)

        module = _load_script_module()
        rc = module.main(["--db-path", str(db_path)])
        assert rc == 0

        row = _read_row(db_path, "bulk-20260526T031148Z")
        assert row is not None
        assert row["status"] == "checking", (
            "Post-reset status MUST be 'checking'. 'investigating' skips Stage 2 and "
            "mis-classifies findings as alive -- see audit lesson 2026-05-22 / #392."
        )
        assert row["quality_aborted"] == 0
        assert row["completed_at"] is None

    def test_recovers_mis_stamped_finding(self, tmp_path: Path) -> None:
        """A finding with state='skipped_alive' but cache says NOT alive
        (404) must be flipped back to 'pending'."""
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path)
        _add_finding(
            db_path,
            run_id="bulk-20260526T031148Z",
            dead_url="https://dead.example/x",
            investigation_state="skipped_alive",
            cache_http_status=404,
        )

        module = _load_script_module()
        module.main(["--db-path", str(db_path)])

        assert _read_finding_state(db_path, "https://dead.example/x") == "pending"

    def test_legitimately_alive_finding_stays_skipped(self, tmp_path: Path) -> None:
        """A finding with state='skipped_alive' AND cache says alive (200)
        must NOT be touched. It's legitimately alive; Stage 3 was right
        to skip it."""
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path)
        _add_finding(
            db_path,
            run_id="bulk-20260526T031148Z",
            dead_url="https://alive.example/x",
            investigation_state="skipped_alive",
            cache_http_status=200,
        )

        module = _load_script_module()
        module.main(["--db-path", str(db_path)])

        assert _read_finding_state(db_path, "https://alive.example/x") == "skipped_alive"

    def test_recovers_finding_with_no_cache_entry(self, tmp_path: Path) -> None:
        """A skipped_alive finding whose dead_url has no url_check_cache
        entry at all (e.g. cache was cleared) must be treated as
        not-confirmed-alive and flipped to pending."""
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path)
        # Insert finding but no cache row
        con = sqlite3.connect(str(db_path))
        try:
            con.execute(
                "INSERT INTO bulk_scan_findings (run_id, dead_url, method, investigation_state) "
                "VALUES (?, ?, 'pending', 'skipped_alive')",
                ("bulk-20260526T031148Z", "https://no-cache.example/x"),
            )
            con.commit()
        finally:
            con.close()

        module = _load_script_module()
        module.main(["--db-path", str(db_path)])

        assert _read_finding_state(db_path, "https://no-cache.example/x") == "pending"

    def test_recovery_count_in_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """AFTER block must show how many findings were recovered."""
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path)
        for i in range(3):
            _add_finding(
                db_path,
                run_id="bulk-20260526T031148Z",
                dead_url=f"https://dead{i}.example/x",
                investigation_state="skipped_alive",
                cache_http_status=404,
            )
        # And one legit alive
        _add_finding(
            db_path,
            run_id="bulk-20260526T031148Z",
            dead_url="https://alive.example/x",
            investigation_state="skipped_alive",
            cache_http_status=200,
        )

        module = _load_script_module()
        module.main(["--db-path", str(db_path)])
        out = capsys.readouterr().out

        after_block = out[out.index("AFTER:") :]
        assert "recovered:        3" in after_block
        assert "mis-stamped:      0" in after_block  # all the bad ones recovered

    def test_emits_resume_command(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path, run_id="some-other-run-id")

        module = _load_script_module()
        module.main(["--db-path", str(db_path), "--run-id", "some-other-run-id"])
        out = capsys.readouterr().out
        assert "bulk-scan start --run-id some-other-run-id" in out


# --- no-op -----------------------------------------------------------------


class TestNoOp:
    def test_returns_zero_when_run_clean_and_no_mis_stamped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path, status="checking", quality_aborted=0, completed_at=None)

        module = _load_script_module()
        rc = module.main(["--db-path", str(db_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "nothing to do" in out

    def test_runs_when_clean_run_status_but_mis_stamped_findings_present(self, tmp_path: Path) -> None:
        """If the run row is already at 'checking'/quality_aborted=0 but
        there are mis-stamped findings, the script MUST still recover
        them. 'Clean' is the conjunction of run state AND finding state."""
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path, status="checking", quality_aborted=0, completed_at=None)
        _add_finding(
            db_path,
            run_id="bulk-20260526T031148Z",
            dead_url="https://dead.example/x",
            investigation_state="skipped_alive",
            cache_http_status=404,
        )

        module = _load_script_module()
        rc = module.main(["--db-path", str(db_path)])
        assert rc == 0
        assert _read_finding_state(db_path, "https://dead.example/x") == "pending"


# --- errors ----------------------------------------------------------------


class TestErrorPaths:
    def test_missing_db_returns_2(self, tmp_path: Path) -> None:
        db_path = tmp_path / "missing.db"

        module = _load_script_module()
        rc = module.main(["--db-path", str(db_path)])
        assert rc == 2

    def test_missing_run_id_returns_3(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path, run_id="someone-elses-run")

        module = _load_script_module()
        rc = module.main(["--db-path", str(db_path), "--run-id", "not-in-db"])
        assert rc == 3


# --- output explanations ---------------------------------------------------


class TestExplanations:
    def test_quality_aborted_shows_yes_not_1(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path)

        module = _load_script_module()
        module.main(["--db-path", str(db_path), "--dry-run"])
        out = capsys.readouterr().out

        before_section = out[out.index("BEFORE:") : out.index("AFTER")]
        assert "yes" in before_section
        assert "quality_aborted:  1\n" not in before_section

    def test_completed_at_unset_uses_human_phrase(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path)

        module = _load_script_module()
        module.main(["--db-path", str(db_path), "--dry-run"])
        out = capsys.readouterr().out
        after_section = out[out.index("AFTER") :]
        assert "unset" in after_section
        assert "completed_at:     None" not in after_section
