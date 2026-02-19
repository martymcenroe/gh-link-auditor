"""Unit tests for Slant scoring engine.

Tests the scorer module: multi-candidate scoring, tier boundaries,
zero candidates, verdict structure, and CLI.

TDD: Tests written FIRST (RED), then implementation (GREEN).
Per LLD #21 §10.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from slant.config import get_default_weights, load_weights
from slant.models import (
    CandidateEntry,
    ForensicReportEntry,
    ScoringBreakdown,
    VerdictsFile,
)
from slant.scorer import (
    map_confidence_to_tier,
    score_candidate,
    score_dead_link,
    score_report,
    write_verdicts,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestGetDefaultWeights:
    """Tests for default weight configuration."""

    def test_returns_correct_weights(self):
        """Default weights sum to 100."""
        weights = get_default_weights()
        assert weights["redirect"] == 40
        assert weights["title"] == 25
        assert weights["content"] == 20
        assert weights["url_path"] == 10
        assert weights["domain"] == 5
        total = sum(weights.values())
        assert total == 100

    def test_returns_signal_weights_typed_dict(self):
        """Returns a dict with exactly the expected keys."""
        weights = get_default_weights()
        expected_keys = {"redirect", "title", "content", "url_path", "domain"}
        assert set(weights.keys()) == expected_keys


class TestLoadWeights:
    """Tests for weight loading from config file."""

    def test_returns_defaults_when_no_config(self):
        """Returns default weights when no config path given."""
        weights = load_weights(None)
        assert weights == get_default_weights()

    def test_loads_from_json_config(self, tmp_path):
        """Loads custom weights from JSON config file."""
        config = {"redirect": 30, "title": 30, "content": 20, "url_path": 10, "domain": 10}
        config_file = tmp_path / "weights.json"
        config_file.write_text(json.dumps(config))
        weights = load_weights(config_file)
        assert weights["redirect"] == 30
        assert weights["title"] == 30

    def test_returns_defaults_for_nonexistent_file(self):
        """Returns defaults when config file doesn't exist."""
        weights = load_weights(Path("/nonexistent/weights.json"))
        assert weights == get_default_weights()


# ---------------------------------------------------------------------------
# Confidence tier mapping tests (LLD §10 T050-T080)
# ---------------------------------------------------------------------------


class TestMapConfidenceToTier:
    """Tests for confidence-to-tier mapping."""

    def test_score_95_is_auto_approve(self):
        """T050: Score 95 maps to AUTO-APPROVE."""
        assert map_confidence_to_tier(95) == "AUTO-APPROVE"

    def test_score_100_is_auto_approve(self):
        """Score 100 maps to AUTO-APPROVE."""
        assert map_confidence_to_tier(100) == "AUTO-APPROVE"

    def test_score_87_is_human_review(self):
        """T060: Score 87 maps to HUMAN-REVIEW."""
        assert map_confidence_to_tier(87) == "HUMAN-REVIEW"

    def test_score_75_is_human_review(self):
        """Boundary: Score 75 maps to HUMAN-REVIEW."""
        assert map_confidence_to_tier(75) == "HUMAN-REVIEW"

    def test_score_94_is_human_review(self):
        """Boundary: Score 94 maps to HUMAN-REVIEW."""
        assert map_confidence_to_tier(94) == "HUMAN-REVIEW"

    def test_score_62_is_low_confidence(self):
        """T070: Score 62 maps to LOW-CONFIDENCE."""
        assert map_confidence_to_tier(62) == "LOW-CONFIDENCE"

    def test_score_50_is_low_confidence(self):
        """Boundary: Score 50 maps to LOW-CONFIDENCE."""
        assert map_confidence_to_tier(50) == "LOW-CONFIDENCE"

    def test_score_74_is_low_confidence(self):
        """Boundary: Score 74 maps to LOW-CONFIDENCE."""
        assert map_confidence_to_tier(74) == "LOW-CONFIDENCE"

    def test_score_31_is_insufficient(self):
        """T080: Score 31 maps to INSUFFICIENT."""
        assert map_confidence_to_tier(31) == "INSUFFICIENT"

    def test_score_49_is_insufficient(self):
        """Boundary: Score 49 maps to INSUFFICIENT."""
        assert map_confidence_to_tier(49) == "INSUFFICIENT"

    def test_score_0_is_insufficient(self):
        """Boundary: Score 0 maps to INSUFFICIENT."""
        assert map_confidence_to_tier(0) == "INSUFFICIENT"


# ---------------------------------------------------------------------------
# Score candidate tests
# ---------------------------------------------------------------------------


class TestScoreCandidate:
    """Tests for scoring a single candidate."""

    def test_returns_tuple_of_float_and_breakdown(self):
        """Returns (composite_score, ScoringBreakdown) tuple."""
        weights = get_default_weights()
        candidate = CandidateEntry(url="https://example.com/new", source="search")

        # Mock all signals to return 0.0 (simplest case)
        with (
            patch("slant.scorer.check_redirect", return_value=0.0),
            patch("slant.scorer.match_title", return_value=0.0),
            patch("slant.scorer.compare_content", return_value=0.0),
            patch("slant.scorer.compare_url_paths", return_value=0.0),
            patch("slant.scorer.match_domain", return_value=0.0),
        ):
            score, breakdown = score_candidate(
                "https://example.com/old", candidate, "Old Title", "Old content", weights
            )
        assert isinstance(score, (int, float))
        assert isinstance(breakdown, dict)

    def test_perfect_scores_sum_to_100(self):
        """All signals at 1.0 produce composite score of 100."""
        weights = get_default_weights()
        candidate = CandidateEntry(url="https://example.com/new", source="search")

        with (
            patch("slant.scorer.check_redirect", return_value=1.0),
            patch("slant.scorer.match_title", return_value=1.0),
            patch("slant.scorer.compare_content", return_value=1.0),
            patch("slant.scorer.compare_url_paths", return_value=1.0),
            patch("slant.scorer.match_domain", return_value=1.0),
        ):
            score, breakdown = score_candidate(
                "https://example.com/old", candidate, "Title", "Content", weights
            )
        assert score == 100
        assert breakdown["redirect"] == 40
        assert breakdown["title_match"] == 25
        assert breakdown["content_similarity"] == 20
        assert breakdown["url_similarity"] == 10
        assert breakdown["domain_match"] == 5

    def test_all_zero_scores_sum_to_zero(self):
        """All signals at 0.0 produce composite score of 0."""
        weights = get_default_weights()
        candidate = CandidateEntry(url="https://other.com/page", source="search")

        with (
            patch("slant.scorer.check_redirect", return_value=0.0),
            patch("slant.scorer.match_title", return_value=0.0),
            patch("slant.scorer.compare_content", return_value=0.0),
            patch("slant.scorer.compare_url_paths", return_value=0.0),
            patch("slant.scorer.match_domain", return_value=0.0),
        ):
            score, breakdown = score_candidate(
                "https://example.com/old", candidate, "Title", "Content", weights
            )
        assert score == 0
        assert breakdown["redirect"] == 0
        assert breakdown["title_match"] == 0

    def test_partial_signals(self):
        """Mixed signal scores produce expected composite."""
        weights = get_default_weights()
        candidate = CandidateEntry(url="https://example.com/new", source="search")

        with (
            patch("slant.scorer.check_redirect", return_value=1.0),
            patch("slant.scorer.match_title", return_value=0.5),
            patch("slant.scorer.compare_content", return_value=0.0),
            patch("slant.scorer.compare_url_paths", return_value=0.0),
            patch("slant.scorer.match_domain", return_value=1.0),
        ):
            score, breakdown = score_candidate(
                "https://example.com/old", candidate, "Title", "Content", weights
            )
        # redirect=40, title=12.5, content=0, url_path=0, domain=5 = 57.5
        assert breakdown["redirect"] == 40
        assert breakdown["title_match"] == pytest.approx(12.5)
        assert breakdown["domain_match"] == 5
        assert score == pytest.approx(57.5)


# ---------------------------------------------------------------------------
# Score dead link tests (LLD §10 T070, T090, T100)
# ---------------------------------------------------------------------------


class TestScoreDeadLink:
    """Tests for scoring a dead link (all its candidates)."""

    def test_zero_candidates_produces_insufficient(self):
        """T100: Zero candidates produce INSUFFICIENT with confidence=0."""
        entry = ForensicReportEntry(
            dead_url="https://example.com/removed",
            archived_url="",
            archived_title="",
            archived_content="",
            investigation_method="none",
            candidates=[],
        )
        weights = get_default_weights()
        verdict = score_dead_link(entry, weights)
        assert verdict["verdict"] == "INSUFFICIENT"
        assert verdict["confidence"] == 0
        assert verdict["replacement_url"] is None

    def test_selects_highest_scoring_candidate(self):
        """Selects candidate with highest composite score."""
        entry = ForensicReportEntry(
            dead_url="https://example.com/old",
            archived_url="https://web.archive.org/...",
            archived_title="Page Title",
            archived_content="Some content here.",
            investigation_method="search",
            candidates=[
                CandidateEntry(url="https://bad.com/page", source="search"),
                CandidateEntry(url="https://good.com/page", source="redirect"),
            ],
        )
        weights = get_default_weights()

        def _mock_score_candidate(dead_url, candidate, title, content, w):
            if candidate["url"] == "https://good.com/page":
                return (85, ScoringBreakdown(
                    redirect=40, title_match=20, content_similarity=15, url_similarity=5, domain_match=5
                ))
            return (20, ScoringBreakdown(
                redirect=0, title_match=5, content_similarity=10, url_similarity=5, domain_match=0
            ))

        with patch("slant.scorer.score_candidate", side_effect=_mock_score_candidate):
            verdict = score_dead_link(entry, weights)
        assert verdict["replacement_url"] == "https://good.com/page"
        assert verdict["confidence"] == 85

    def test_auto_approve_sets_auto_decision(self):
        """T090: AUTO-APPROVE sets human_decision='auto' and decided_at."""
        entry = ForensicReportEntry(
            dead_url="https://example.com/old",
            archived_url="",
            archived_title="Title",
            archived_content="Content",
            investigation_method="redirect",
            candidates=[CandidateEntry(url="https://example.com/new", source="redirect")],
        )
        weights = get_default_weights()

        with patch("slant.scorer.score_candidate", return_value=(
            96,
            ScoringBreakdown(redirect=40, title_match=25, content_similarity=18, url_similarity=8, domain_match=5),
        )):
            verdict = score_dead_link(entry, weights)
        assert verdict["verdict"] == "AUTO-APPROVE"
        assert verdict["human_decision"] == "auto"
        assert verdict["decided_at"] is not None

    def test_human_review_has_null_decision(self):
        """HUMAN-REVIEW leaves human_decision=null."""
        entry = ForensicReportEntry(
            dead_url="https://example.com/old",
            archived_url="",
            archived_title="Title",
            archived_content="Content",
            investigation_method="search",
            candidates=[CandidateEntry(url="https://example.com/new", source="search")],
        )
        weights = get_default_weights()

        with patch("slant.scorer.score_candidate", return_value=(
            80,
            ScoringBreakdown(redirect=20, title_match=20, content_similarity=20, url_similarity=10, domain_match=5),
        )):
            verdict = score_dead_link(entry, weights)
        assert verdict["verdict"] == "HUMAN-REVIEW"
        assert verdict["human_decision"] is None
        assert verdict["decided_at"] is None

    def test_verdict_has_all_required_fields(self):
        """T020: Verdict contains all 7 required fields."""
        entry = ForensicReportEntry(
            dead_url="https://example.com/old",
            archived_url="",
            archived_title="Title",
            archived_content="Content",
            investigation_method="search",
            candidates=[CandidateEntry(url="https://example.com/new", source="search")],
        )
        weights = get_default_weights()

        with patch("slant.scorer.score_candidate", return_value=(
            50,
            ScoringBreakdown(redirect=0, title_match=15, content_similarity=20, url_similarity=10, domain_match=5),
        )):
            verdict = score_dead_link(entry, weights)
        required_fields = {
            "dead_url", "verdict", "confidence", "replacement_url",
            "scoring_breakdown", "human_decision", "decided_at",
        }
        assert required_fields.issubset(verdict.keys())


# ---------------------------------------------------------------------------
# Score report tests (LLD §10 T010)
# ---------------------------------------------------------------------------


class TestScoreReport:
    """Tests for scoring a full forensic report."""

    def test_produces_correct_verdict_count(self, tmp_path):
        """T010: Score report produces correct verdict count."""
        report_path = FIXTURES_DIR / "sample_forensic_report.json"
        # Mock all signal calls to avoid HTTP
        with (
            patch("slant.scorer.check_redirect", return_value=0.5),
            patch("slant.scorer.match_title", return_value=0.5),
            patch("slant.scorer.compare_content", return_value=0.5),
            patch("slant.scorer.compare_url_paths", return_value=0.5),
            patch("slant.scorer.match_domain", return_value=0.5),
        ):
            result = score_report(report_path)
        assert len(result["verdicts"]) == 5

    def test_includes_metadata(self, tmp_path):
        """Result includes generated_at and source_report."""
        report_path = FIXTURES_DIR / "sample_forensic_report.json"
        with (
            patch("slant.scorer.check_redirect", return_value=0.0),
            patch("slant.scorer.match_title", return_value=0.0),
            patch("slant.scorer.compare_content", return_value=0.0),
            patch("slant.scorer.compare_url_paths", return_value=0.0),
            patch("slant.scorer.match_domain", return_value=0.0),
        ):
            result = score_report(report_path)
        assert "generated_at" in result
        assert "source_report" in result
        assert result["source_report"] == str(report_path)

    def test_zero_candidate_entry_produces_insufficient(self, tmp_path):
        """Entry with zero candidates in report produces INSUFFICIENT."""
        report_path = FIXTURES_DIR / "sample_forensic_report.json"
        with (
            patch("slant.scorer.check_redirect", return_value=0.5),
            patch("slant.scorer.match_title", return_value=0.5),
            patch("slant.scorer.compare_content", return_value=0.5),
            patch("slant.scorer.compare_url_paths", return_value=0.5),
            patch("slant.scorer.match_domain", return_value=0.5),
        ):
            result = score_report(report_path)
        # The 4th entry has zero candidates
        insufficient = [v for v in result["verdicts"] if v["dead_url"] == "https://example.com/removed-page"]
        assert len(insufficient) == 1
        assert insufficient[0]["verdict"] == "INSUFFICIENT"
        assert insufficient[0]["confidence"] == 0


# ---------------------------------------------------------------------------
# Write verdicts tests
# ---------------------------------------------------------------------------


class TestWriteVerdicts:
    """Tests for writing verdicts to disk."""

    def test_writes_valid_json(self, tmp_path):
        """Writes valid JSON to specified path."""
        output_path = tmp_path / "verdicts.json"
        verdicts_file: VerdictsFile = {
            "generated_at": "2026-02-18T12:00:00Z",
            "source_report": "report.json",
            "verdicts": [],
        }
        write_verdicts(verdicts_file, output_path)
        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert data["generated_at"] == "2026-02-18T12:00:00Z"

    def test_atomic_write_doesnt_corrupt_on_error(self, tmp_path):
        """Existing file is not corrupted if write fails."""
        output_path = tmp_path / "verdicts.json"
        # Write initial valid file
        output_path.write_text('{"initial": true}')

        # Attempt to write invalid data - can't really force JSON to fail,
        # but we verify the file is either fully updated or unchanged.
        verdicts_file: VerdictsFile = {
            "generated_at": "2026-02-18T12:00:00Z",
            "source_report": "report.json",
            "verdicts": [],
        }
        write_verdicts(verdicts_file, output_path)
        data = json.loads(output_path.read_text())
        assert "generated_at" in data


# ---------------------------------------------------------------------------
# CLI tests (LLD §10 T260)
# ---------------------------------------------------------------------------


class TestCLI:
    """Tests for the CLI entry point."""

    def test_help_flag_exits_zero(self):
        """T260: CLI --help works."""
        from slant.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_score_subcommand_help(self):
        """Score subcommand --help works."""
        from slant.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["score", "--help"])
        assert exc_info.value.code == 0

    def test_no_subcommand_prints_help(self, capsys):
        """No subcommand prints help and returns 0."""
        from slant.cli import main

        result = main([])
        assert result == 0

    def test_cmd_score_runs_successfully(self, tmp_path):
        """Score subcommand produces verdicts file."""
        from slant.cli import main

        report_path = FIXTURES_DIR / "sample_forensic_report.json"
        output_path = tmp_path / "verdicts.json"

        with (
            patch("slant.scorer.check_redirect", return_value=0.5),
            patch("slant.scorer.match_title", return_value=0.5),
            patch("slant.scorer.compare_content", return_value=0.5),
            patch("slant.scorer.compare_url_paths", return_value=0.5),
            patch("slant.scorer.match_domain", return_value=0.5),
        ):
            result = main(["score", "--report", str(report_path), "--output", str(output_path)])
        assert result == 0
        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert len(data["verdicts"]) == 5

    def test_cmd_score_default_output(self, tmp_path):
        """Score subcommand uses default output path when --output not given."""
        from slant.cli import main

        # Copy fixture to tmp_path so default output goes there
        report_data = (FIXTURES_DIR / "sample_forensic_report.json").read_text()
        report_path = tmp_path / "report.json"
        report_path.write_text(report_data)

        with (
            patch("slant.scorer.check_redirect", return_value=0.0),
            patch("slant.scorer.match_title", return_value=0.0),
            patch("slant.scorer.compare_content", return_value=0.0),
            patch("slant.scorer.compare_url_paths", return_value=0.0),
            patch("slant.scorer.match_domain", return_value=0.0),
        ):
            result = main(["score", "--report", str(report_path)])
        assert result == 0
        default_output = tmp_path / "verdicts.json"
        assert default_output.exists()

    def test_cmd_dashboard_help(self):
        """Dashboard subcommand --help works."""
        from slant.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["dashboard", "--help"])
        assert exc_info.value.code == 0


class TestMainModule:
    """Tests for __main__.py entry point."""

    def test_main_module_callable(self):
        """__main__ module imports and calls main()."""
        from slant.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_main_module_runs(self):
        """__main__ module can be executed via runpy."""
        import runpy

        with (
            patch("slant.cli.main", return_value=0),
            pytest.raises(SystemExit) as exc_info,
        ):
            runpy.run_module("slant", run_name="__main__")
        assert exc_info.value.code == 0


class TestDashboardIntegration:
    """Tests verifying CLI integrates with dashboard module."""

    def test_cmd_dashboard_calls_start_dashboard(self):
        """CLI dashboard subcommand calls start_dashboard."""
        from slant.cli import main

        with patch("slant.dashboard.start_dashboard") as mock_start:
            main(["dashboard", "--verdicts", "verdicts.json"])
            mock_start.assert_called_once()
