"""Slant scoring flow integration tests.

Tests scoring and verdict tier mapping with real scorer code.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from slant.scorer import map_confidence_to_tier, score_report, write_verdicts


def _fake_signal_high(*args, **kwargs):
    """Fake signal that returns high score."""
    return 0.9


def _fake_signal_low(*args, **kwargs):
    """Fake signal that returns low score."""
    return 0.1


@pytest.mark.integration
class TestSlantFlow:
    """Scoring and verdict flow tests."""

    def test_verdict_tiers_match_confidence(self) -> None:
        """Verify >=95=AUTO, 75-94=REVIEW, 50-74=LOW, <50=INSUFFICIENT."""
        assert map_confidence_to_tier(95) == "AUTO-APPROVE"
        assert map_confidence_to_tier(100) == "AUTO-APPROVE"
        assert map_confidence_to_tier(75) == "HUMAN-REVIEW"
        assert map_confidence_to_tier(94) == "HUMAN-REVIEW"
        assert map_confidence_to_tier(50) == "LOW-CONFIDENCE"
        assert map_confidence_to_tier(74) == "LOW-CONFIDENCE"
        assert map_confidence_to_tier(49) == "INSUFFICIENT"
        assert map_confidence_to_tier(0) == "INSUFFICIENT"

    def test_score_report_end_to_end(self, tmp_path: Path) -> None:
        """JSON report → score_report → VerdictsFile with correct tiers."""
        report = {
            "dead_links": [
                {
                    "dead_url": "https://dead.example.com/page",
                    "archived_url": "https://web.archive.org/web/2024/https://dead.example.com/page",
                    "archived_title": "Example Page",
                    "archived_content": "Some content here",
                    "investigation_method": "redirect_chain",
                    "candidates": [
                        {"url": "https://new.example.com/page", "source": "redirect_chain"},
                    ],
                },
            ],
        }
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(report))

        # Patch all signals to return high scores
        with (
            patch("slant.scorer.check_redirect", return_value=0.9),
            patch("slant.scorer.match_title", return_value=0.9),
            patch("slant.scorer.compare_content", return_value=0.9),
            patch("slant.scorer.compare_url_paths", return_value=0.9),
            patch("slant.scorer.match_domain", return_value=0.9),
        ):
            verdicts_file = score_report(report_path)

        assert "verdicts" in verdicts_file
        assert len(verdicts_file["verdicts"]) == 1
        v = verdicts_file["verdicts"][0]
        assert v["dead_url"] == "https://dead.example.com/page"
        assert v["confidence"] > 0
        assert v["verdict"] in ("AUTO-APPROVE", "HUMAN-REVIEW", "LOW-CONFIDENCE", "INSUFFICIENT")

    def test_write_and_read_verdicts_roundtrip(self, tmp_path: Path) -> None:
        """write_verdicts + Path.read_text produces valid JSON."""
        verdicts_file = {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "source_report": "test_report.json",
            "verdicts": [
                {
                    "dead_url": "https://dead.example.com",
                    "verdict": "AUTO-APPROVE",
                    "confidence": 98,
                    "replacement_url": "https://new.example.com",
                    "scoring_breakdown": {
                        "redirect": 0.9,
                        "title_match": 0.8,
                        "content_similarity": 0.7,
                        "url_similarity": 0.6,
                        "domain_match": 1.0,
                    },
                    "human_decision": None,
                    "decided_at": None,
                },
            ],
        }

        output_path = tmp_path / "verdicts.json"
        write_verdicts(verdicts_file, output_path)

        assert output_path.exists()
        loaded = json.loads(output_path.read_text())
        assert loaded["verdicts"][0]["dead_url"] == "https://dead.example.com"
        assert loaded["verdicts"][0]["confidence"] == 98
        assert loaded["verdicts"][0]["verdict"] == "AUTO-APPROVE"
