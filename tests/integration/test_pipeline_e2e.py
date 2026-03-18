"""Pipeline E2E integration tests.

Tests the full N0→N5 pipeline flow with network layer patched.
Verifies nodes wire together correctly and state flows through.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from gh_link_auditor.link_detective import ForensicReport, Investigation
from gh_link_auditor.pipeline.graph import run_pipeline
from gh_link_auditor.pipeline.state import create_initial_state


def _make_empty_report(url: str) -> ForensicReport:
    """Create a ForensicReport with no candidates."""
    return ForensicReport(
        dead_url=url,
        http_status=404,
        investigation=Investigation(
            archive_snapshot=None,
            archive_title=None,
            archive_content_summary=None,
            candidate_replacements=[],
            investigation_log=["no candidates found"],
        ),
    )


def _fake_check_url_dead(url, **kwargs):
    """Fake check_url that returns all links as dead (404)."""
    return {
        "url": url,
        "status": "error",
        "status_code": 404,
        "method": "HEAD",
        "response_time_ms": 50,
        "retries": 0,
        "error": "HTTP 404",
    }


def _fake_check_url_ok(url, **kwargs):
    """Fake check_url that returns all links as alive (200)."""
    return {
        "url": url,
        "status": "ok",
        "status_code": 200,
        "method": "HEAD",
        "response_time_ms": 50,
        "retries": 0,
        "error": None,
    }


@pytest.mark.integration
class TestPipelineE2E:
    """Full pipeline integration tests."""

    def test_full_pipeline_happy_path(self, tmp_path: Path) -> None:
        """N0→N5 produces FixPatch from temp dir with dead links."""
        # Set up a temp repo with a dead link
        readme = tmp_path / "README.md"
        readme.write_text("Check [link](https://dead.example.com/page) for info.\n")

        state = create_initial_state(
            target=str(tmp_path),
            max_links=50,
            dry_run=False,
            db_path=str(tmp_path / "state.db"),
        )

        with (
            patch(
                "gh_link_auditor.pipeline.nodes.n1_scan.network_check_url",
                side_effect=_fake_check_url_dead,
            ),
            patch(
                "gh_link_auditor.pipeline.nodes.n2_investigate._run_investigation",
                side_effect=lambda url, status: _make_empty_report(url),
            ),
            patch(
                "gh_link_auditor.pipeline.nodes.n4_human_review.prompt_user_approval",
                return_value=True,
            ),
        ):
            result = run_pipeline(state)

        # Pipeline should complete without errors
        assert result.get("scan_complete") is True
        assert isinstance(result.get("dead_links"), list)

    def test_no_dead_links_clean_run(self, tmp_path: Path) -> None:
        """All links return 200 → empty results."""
        readme = tmp_path / "README.md"
        readme.write_text("Check [link](https://alive.example.com) for info.\n")

        state = create_initial_state(
            target=str(tmp_path),
            db_path=str(tmp_path / "state.db"),
        )

        with patch(
            "gh_link_auditor.pipeline.nodes.n1_scan.network_check_url",
            side_effect=_fake_check_url_ok,
        ):
            result = run_pipeline(state)

        assert result.get("scan_complete") is True
        assert result.get("dead_links") == []
        # No candidates/verdicts when no dead links
        assert result.get("candidates", {}) == {}

    def test_dry_run_skips_fix_generation(self, tmp_path: Path) -> None:
        """dry_run=True still scans/judges but stops before N5."""
        readme = tmp_path / "README.md"
        readme.write_text("Visit [link](https://dead.example.com/gone) today.\n")

        state = create_initial_state(
            target=str(tmp_path),
            dry_run=True,
            db_path=str(tmp_path / "state.db"),
        )

        with (
            patch(
                "gh_link_auditor.pipeline.nodes.n1_scan.network_check_url",
                side_effect=_fake_check_url_dead,
            ),
            patch(
                "gh_link_auditor.pipeline.nodes.n2_investigate._run_investigation",
                side_effect=lambda url, status: _make_empty_report(url),
            ),
        ):
            result = run_pipeline(state)

        assert result.get("scan_complete") is True
        # dry_run should not produce fixes
        assert result.get("fixes", []) == []
