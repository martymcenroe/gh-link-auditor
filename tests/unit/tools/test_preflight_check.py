"""Tests for tools/preflight_check.py (#283 scaffold)."""

from __future__ import annotations

from pathlib import Path

from gh_link_auditor.preflight.report import PreflightReport, PreflightVerdict
from tools.preflight_check import (
    DEFAULT_REPORT_DIR,
    DEFAULT_THRESHOLD,
    _build_parser,
    _make_run_id,
    main,
    run_preflight,
)


class TestBuildParser:
    def test_required_repo(self):
        # parser exits when --repo missing
        import pytest

        with pytest.raises(SystemExit):
            _build_parser().parse_args([])

    def test_all_flag_defaults(self):
        args = _build_parser().parse_args(["--repo", "owner/r"])
        assert args.repo == "owner/r"
        assert args.candidate_id is None
        assert args.report is False
        assert args.score_only is False
        assert args.strict is False
        assert args.threshold == DEFAULT_THRESHOLD
        assert args.preflight_log_dir == DEFAULT_REPORT_DIR

    def test_explicit_flags(self, tmp_path):
        args = _build_parser().parse_args(
            [
                "--repo",
                "o/r",
                "--candidate-id",
                "abc123",
                "--report",
                "--score-only",
                "--strict",
                "--threshold",
                "85",
                "--preflight-log-dir",
                str(tmp_path),
            ]
        )
        assert args.repo == "o/r"
        assert args.candidate_id == "abc123"
        assert args.report is True
        assert args.score_only is True
        assert args.strict is True
        assert args.threshold == 85
        assert args.preflight_log_dir == tmp_path


class TestMakeRunId:
    def test_format(self):
        run_id = _make_run_id()
        assert run_id.startswith("preflight-")
        # Should have a timestamp segment and a short hex suffix
        parts = run_id.split("-")
        assert len(parts) >= 3
        assert "T" in parts[1] and parts[1].endswith("Z")
        assert len(parts[-1]) == 6


class TestRunPreflightScaffold:
    """The scaffold's ``run_preflight`` returns PASS with no evaluations.

    Real gate / score dispatch lands in subsequent PRs under #281.
    """

    def test_returns_preflight_report(self):
        # gates=[] exercises the scaffold-style PASS path without invoking
        # real GitHub / network collaborators (#289).
        report = run_preflight(
            "owner/r",
            {"dead_url": "https://a", "candidate_url": "https://b"},
            gates=[],
        )
        assert isinstance(report, PreflightReport)
        assert report.repo_full_name == "owner/r"
        assert report.verdict == PreflightVerdict.PASS
        assert report.score == DEFAULT_THRESHOLD
        assert report.threshold == DEFAULT_THRESHOLD
        assert report.gate_results == []
        assert report.score_breakdown == []
        assert report.run_id.startswith("preflight-")

    def test_custom_threshold_passed_through(self):
        report = run_preflight(
            "owner/r",
            {"dead_url": "https://a", "candidate_url": "https://b"},
            threshold=85,
            gates=[],
        )
        assert report.threshold == 85
        assert report.score == 85

    def test_explicit_run_id_used(self):
        report = run_preflight(
            "owner/r",
            {"dead_url": "https://a", "candidate_url": "https://b"},
            run_id="caller-supplied-id",
            gates=[],
        )
        assert report.run_id == "caller-supplied-id"

    def test_candidate_is_copied_not_shared(self):
        candidate = {"dead_url": "https://a", "candidate_url": "https://b"}
        report = run_preflight("owner/r", candidate, gates=[])
        candidate["dead_url"] = "MUTATED"
        assert report.candidate["dead_url"] == "https://a"


class TestRunPreflightDispatch:
    """Verify run_preflight's gate dispatch routes correctly (#289)."""

    def test_passing_gate_continues_to_pass_verdict(self):
        from gh_link_auditor.preflight.report import GateResult

        def fake_pass_gate(repo, candidate, db):
            return GateResult(name="fake_pass", passed=True, reason="ok", evidence={"x": 1})

        report = run_preflight(
            "owner/r",
            {"dead_url": "https://a", "candidate_url": "https://b"},
            gates=[fake_pass_gate],
        )
        assert report.verdict == PreflightVerdict.PASS
        assert len(report.gate_results) == 1
        assert report.gate_results[0].name == "fake_pass"

    def test_failing_gate_short_circuits(self):
        from gh_link_auditor.preflight.report import GateResult

        def fake_fail_gate(repo, candidate, db):
            return GateResult(name="fake_fail", passed=False, reason="boom", evidence={})

        def should_not_run(repo, candidate, db):
            raise AssertionError("subsequent gate should not run after a fail")

        report = run_preflight(
            "owner/r",
            {"dead_url": "https://a", "candidate_url": "https://b"},
            gates=[fake_fail_gate, should_not_run],
        )
        assert report.verdict == PreflightVerdict.HARD_GATE_FAILED
        assert report.gate_failure_name == "fake_fail"
        assert len(report.gate_results) == 1  # short-circuit

    def test_score_too_low_when_components_below_threshold(self):
        from gh_link_auditor.preflight.report import ScoreComponent

        def fake_score(repo, candidate, db):
            return ScoreComponent(name="fake", points_awarded=10, max_points=100, evidence={})

        report = run_preflight(
            "owner/r",
            {"dead_url": "https://a", "candidate_url": "https://b"},
            gates=[],
            score_components=[fake_score],
        )
        assert report.verdict == PreflightVerdict.SCORE_TOO_LOW
        assert report.score == 10


class TestMain:
    def _patch_gates_empty(self, monkeypatch):
        import tools.preflight_check as tpc
        from gh_link_auditor.preflight import gates as gates_mod

        monkeypatch.setattr(gates_mod, "HARD_GATES", [])
        monkeypatch.setattr(tpc, "HARD_GATES", [])

    def test_exit_zero_on_pass(self, capsys, monkeypatch):
        self._patch_gates_empty(monkeypatch)
        rc = main(["--repo", "owner/r"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "verdict=pass" in out

    def test_strict_returns_zero_when_pass(self, capsys, monkeypatch):
        self._patch_gates_empty(monkeypatch)
        rc = main(["--repo", "owner/r", "--strict"])
        assert rc == 0

    def test_score_only_prints_int(self, capsys, monkeypatch):
        self._patch_gates_empty(monkeypatch)
        rc = main(["--repo", "owner/r", "--score-only"])
        out = capsys.readouterr().out.strip()
        assert rc == 0
        assert out == str(DEFAULT_THRESHOLD)

    def test_report_writes_files(self, tmp_path, capsys, monkeypatch):
        self._patch_gates_empty(monkeypatch)
        rc = main(["--repo", "owner/r", "--report", "--preflight-log-dir", str(tmp_path)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "markdown:" in out
        assert "json:" in out
        files = list(tmp_path.iterdir())
        suffixes = sorted(f.suffix for f in files)
        assert suffixes == [".json", ".md"]

    def test_default_report_dir_constant_is_data_preflight_reports(self):
        # Sanity check: the default ends with data/preflight-reports
        assert DEFAULT_REPORT_DIR.parts[-2:] == ("data", "preflight-reports")

    def test_default_report_dir_under_project(self):
        # Make sure DEFAULT_REPORT_DIR points at the repo, not the cwd
        assert isinstance(DEFAULT_REPORT_DIR, Path)
