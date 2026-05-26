"""Tests for tools/reset_quality_aborted.py.

The script is an operational recovery helper that mutates a local
SQLite DB. These tests exercise it against a tmp_path DB seeded with
the bulk_scan_runs schema, so the agent (or anyone else) can validate
output and behavior without touching the operator's real ~/.ghla/ghla.db.
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
    # Avoid polluting sys.modules permanently across test sessions.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _seed_run(
    db_path: Path,
    *,
    run_id: str = "bulk-20260526T031148Z",
    status: str = "quality_aborted",
    quality_aborted: int = 1,
    completed_at: str | None = "2026-05-26T05:31:09.021709+00:00",
) -> None:
    """Create a minimal bulk_scan_runs row matching the production schema
    fields the script touches. The script only references status,
    quality_aborted, and completed_at, so we keep the fixture narrow."""
    con = sqlite3.connect(str(db_path))
    try:
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
            "INSERT INTO bulk_scan_runs (run_id, status, quality_aborted, completed_at) VALUES (?, ?, ?, ?)",
            (run_id, status, quality_aborted, completed_at),
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


# --- dry-run ---------------------------------------------------------------


class TestDryRun:
    def test_does_not_mutate_db(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path)

        module = _load_script_module()
        rc = module.main(["--db-path", str(db_path), "--dry-run"])

        assert rc == 0
        # DB unchanged
        row = _read_row(db_path, "bulk-20260526T031148Z")
        assert row is not None
        assert row["status"] == "quality_aborted"
        assert row["quality_aborted"] == 1
        assert row["completed_at"] == "2026-05-26T05:31:09.021709+00:00"

    def test_shows_projected_clean_state(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Regression test for the bug the operator caught: dry-run was
        re-reading the unchanged row, so the AFTER block showed the same
        values as BEFORE. AFTER must reflect the PROJECTED post-update
        state, not a re-read of the still-aborted row."""
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path)

        module = _load_script_module()
        module.main(["--db-path", str(db_path), "--dry-run"])
        out = capsys.readouterr().out

        assert "BEFORE:" in out
        assert "AFTER (projected; not written):" in out

        # Split into BEFORE / AFTER sections so we can pin each separately.
        before_idx = out.index("BEFORE:")
        after_idx = out.index("AFTER (projected; not written):")
        before_block = out[before_idx:after_idx]
        after_block = out[after_idx:]

        # BEFORE must show the aborted state.
        assert "quality_aborted" in before_block
        assert "yes" in before_block
        assert "2026-05-26T05:31:09" in before_block

        # AFTER must show the clean state -- this is the bug the operator
        # found: previously the AFTER block matched BEFORE.
        assert "investigating" in after_block
        assert "no   --" in after_block
        assert "2026-05-26T05:31:09" not in after_block, "AFTER must not show the old completed_at"
        assert "unset" in after_block

    def test_prints_followup_hint(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path)

        module = _load_script_module()
        module.main(["--db-path", str(db_path), "--dry-run"])
        out = capsys.readouterr().out
        assert "re-run without --dry-run to apply" in out


# --- apply -----------------------------------------------------------------


class TestApply:
    def test_mutates_db(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path)

        module = _load_script_module()
        rc = module.main(["--db-path", str(db_path)])
        assert rc == 0

        row = _read_row(db_path, "bulk-20260526T031148Z")
        assert row is not None
        assert row["status"] == "investigating"
        assert row["quality_aborted"] == 0
        assert row["completed_at"] is None

    def test_after_block_shows_actual_db_state(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """When applying, AFTER reflects the post-UPDATE DB read, not a
        synthesized projection. Pins that distinction so a refactor can't
        accidentally drop the verify step."""
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path)

        module = _load_script_module()
        module.main(["--db-path", str(db_path)])
        out = capsys.readouterr().out

        # Header must be the non-dry-run variant.
        assert "AFTER:" in out
        assert "AFTER (projected; not written):" not in out

        # And the resume hint must appear.
        assert "bulk-scan start --run-id bulk-20260526T031148Z" in out

    def test_emits_resume_command(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path, run_id="some-other-run-id")

        module = _load_script_module()
        module.main(["--db-path", str(db_path), "--run-id", "some-other-run-id"])
        out = capsys.readouterr().out
        assert "bulk-scan start --run-id some-other-run-id" in out


# --- no-op -----------------------------------------------------------------


class TestNoOp:
    def test_returns_zero_and_does_not_mutate_when_already_clean(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path, status="investigating", quality_aborted=0, completed_at=None)

        module = _load_script_module()
        rc = module.main(["--db-path", str(db_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "nothing to do" in out

        # Still the same row.
        row = _read_row(db_path, "bulk-20260526T031148Z")
        assert row is not None
        assert row["status"] == "investigating"


# --- errors ----------------------------------------------------------------


class TestErrorPaths:
    def test_missing_db_returns_2(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        db_path = tmp_path / "missing.db"

        module = _load_script_module()
        rc = module.main(["--db-path", str(db_path)])
        assert rc == 2

    def test_missing_run_id_returns_3(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path, run_id="someone-elses-run")

        module = _load_script_module()
        rc = module.main(["--db-path", str(db_path), "--run-id", "not-in-db"])
        assert rc == 3


# --- output explanations ---------------------------------------------------


class TestExplanations:
    """Pin the human-readable explanation strings the operator asked for
    (no raw 0/1 sqlite booleans in the output)."""

    def test_quality_aborted_shows_yes_not_1(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path)

        module = _load_script_module()
        module.main(["--db-path", str(db_path), "--dry-run"])
        out = capsys.readouterr().out

        # BEFORE half must contain 'yes' (the human form), not raw 1.
        before_section = out[out.index("BEFORE:") : out.index("AFTER")]
        assert "yes" in before_section
        assert "quality_aborted:  1\n" not in before_section
        assert "quality_aborted:  0\n" not in before_section

    def test_completed_at_unset_uses_human_phrase(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        db_path = tmp_path / "ghla.db"
        _seed_run(db_path)

        module = _load_script_module()
        module.main(["--db-path", str(db_path), "--dry-run"])
        out = capsys.readouterr().out
        after_section = out[out.index("AFTER") :]
        assert "unset" in after_section
        # Should NOT show the literal string "None" instead of the explanation
        assert "completed_at:     None" not in after_section
