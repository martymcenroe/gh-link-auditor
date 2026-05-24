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
        report = run_preflight("owner/r", {"dead_url": "https://a", "candidate_url": "https://b"})
        assert isinstance(report, PreflightReport)
        assert report.repo_full_name == "owner/r"
        assert report.verdict == PreflightVerdict.PASS
        assert report.score == 0
        assert report.threshold == DEFAULT_THRESHOLD
        assert report.gate_results == []
        assert report.score_breakdown == []
        assert report.run_id.startswith("preflight-")

    def test_custom_threshold_passed_through(self):
        report = run_preflight("owner/r", {"dead_url": "https://a", "candidate_url": "https://b"}, threshold=85)
        assert report.threshold == 85

    def test_explicit_run_id_used(self):
        report = run_preflight(
            "owner/r",
            {"dead_url": "https://a", "candidate_url": "https://b"},
            run_id="caller-supplied-id",
        )
        assert report.run_id == "caller-supplied-id"

    def test_candidate_is_copied_not_shared(self):
        candidate = {"dead_url": "https://a", "candidate_url": "https://b"}
        report = run_preflight("owner/r", candidate)
        candidate["dead_url"] = "MUTATED"
        # report.candidate should not have been mutated through the dict identity
        assert report.candidate["dead_url"] == "https://a"


class TestMain:
    def test_exit_zero_on_pass(self, capsys):
        rc = main(["--repo", "owner/r"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "verdict=pass" in out

    def test_strict_returns_zero_when_pass(self, capsys):
        rc = main(["--repo", "owner/r", "--strict"])
        assert rc == 0

    def test_score_only_prints_int(self, capsys):
        rc = main(["--repo", "owner/r", "--score-only"])
        out = capsys.readouterr().out.strip()
        assert rc == 0
        assert out == "0"

    def test_report_writes_files(self, tmp_path, capsys):
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
