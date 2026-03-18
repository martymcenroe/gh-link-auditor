"""Tests for N2 Investigate node.

See LLD #22 §10.0 T100/T110: N2 Wayback success, no candidates.
"""

from __future__ import annotations

from unittest.mock import patch

from gh_link_auditor.link_detective import (
    CandidateReplacement,
    ForensicReport,
    Investigation,
    InvestigationMethod,
)
from gh_link_auditor.pipeline.nodes.n2_investigate import (
    investigate_dead_link,
    n2_investigate,
)
from gh_link_auditor.pipeline.state import DeadLink, create_initial_state


def _make_dead_link(url: str = "https://example.com/broken") -> DeadLink:
    return DeadLink(
        url=url,
        source_file="README.md",
        line_number=10,
        link_text="broken link",
        http_status=404,
        error_type="http_error",
    )


class TestRunInvestigation:
    """Tests for _run_investigation() lazy import (lines 31-34)."""

    def test_lazy_import_calls_link_detective(self) -> None:
        """_run_investigation lazily imports and calls LinkDetective.investigate."""
        from gh_link_auditor.pipeline.nodes.n2_investigate import _run_investigation

        report = ForensicReport(
            dead_url="https://example.com/dead",
            http_status=404,
            investigation=Investigation(
                archive_snapshot=None,
                archive_title=None,
                archive_content_summary=None,
                candidate_replacements=[],
                investigation_log=["test"],
            ),
        )

        with patch(
            "gh_link_auditor.link_detective.LinkDetective.investigate",
            return_value=report,
        ):
            result = _run_investigation("https://example.com/dead", 404)

        assert result.dead_url == "https://example.com/dead"


class TestInvestigateDeadLink:
    """Tests for investigate_dead_link()."""

    def test_returns_candidates_from_investigation(self) -> None:
        report = ForensicReport(
            dead_url="https://example.com/broken",
            http_status=404,
            investigation=Investigation(
                archive_snapshot="https://web.archive.org/web/2024/https://example.com/broken",
                archive_title="Example Page",
                archive_content_summary="Some content",
                candidate_replacements=[
                    CandidateReplacement(
                        url="https://example.com/new-page",
                        method=InvestigationMethod.REDIRECT_CHAIN,
                        similarity_score=0.95,
                        verified_live=True,
                    ),
                ],
                investigation_log=["test"],
            ),
        )
        with patch(
            "gh_link_auditor.pipeline.nodes.n2_investigate._run_investigation",
            return_value=report,
        ):
            dead_link = _make_dead_link()
            candidates = investigate_dead_link(dead_link)
        assert len(candidates) >= 1
        assert candidates[0]["url"] == "https://example.com/new-page"

    def test_returns_empty_when_no_candidates(self) -> None:
        report = ForensicReport(
            dead_url="https://example.com/gone",
            http_status=404,
            investigation=Investigation(
                archive_snapshot=None,
                archive_title=None,
                archive_content_summary=None,
                candidate_replacements=[],
                investigation_log=["no candidates"],
            ),
        )
        with patch(
            "gh_link_auditor.pipeline.nodes.n2_investigate._run_investigation",
            return_value=report,
        ):
            candidates = investigate_dead_link(_make_dead_link("https://example.com/gone"))
        assert candidates == []

    def test_handles_investigation_error(self) -> None:
        with patch(
            "gh_link_auditor.pipeline.nodes.n2_investigate._run_investigation",
            side_effect=Exception("network error"),
        ):
            candidates = investigate_dead_link(_make_dead_link())
        assert candidates == []


class TestN2Investigate:
    """Tests for n2_investigate() node function."""

    def test_populates_candidates(self) -> None:
        state = create_initial_state(target="t")
        state["dead_links"] = [_make_dead_link()]
        mock_candidates = [
            {
                "url": "https://example.com/new",
                "source": "redirect_chain",
                "title": "New Page",
                "snippet": None,
            }
        ]
        with patch(
            "gh_link_auditor.pipeline.nodes.n2_investigate.investigate_dead_link",
            return_value=mock_candidates,
        ):
            result = n2_investigate(state)
        assert "https://example.com/broken" in result["candidates"]
        assert len(result["candidates"]["https://example.com/broken"]) == 1

    def test_empty_dead_links(self) -> None:
        state = create_initial_state(target="t")
        state["dead_links"] = []
        result = n2_investigate(state)
        assert result["candidates"] == {}

    def test_handles_cost_limit(self) -> None:
        state = create_initial_state(target="t")
        state["dead_links"] = [_make_dead_link()]
        state["cost_limit_reached"] = True
        result = n2_investigate(state)
        # Should skip investigation when cost limit reached
        assert result.get("candidates", {}) == {} or result["cost_limit_reached"] is True

    def test_multiple_dead_links(self) -> None:
        state = create_initial_state(target="t")
        state["dead_links"] = [
            _make_dead_link("https://a.com/dead"),
            _make_dead_link("https://b.com/dead"),
        ]
        with patch(
            "gh_link_auditor.pipeline.nodes.n2_investigate.investigate_dead_link",
            return_value=[],
        ):
            result = n2_investigate(state)
        assert "https://a.com/dead" in result["candidates"]
        assert "https://b.com/dead" in result["candidates"]

    def test_error_handling(self) -> None:
        state = create_initial_state(target="t")
        state["dead_links"] = [_make_dead_link()]
        with patch(
            "gh_link_auditor.pipeline.nodes.n2_investigate.investigate_dead_link",
            side_effect=Exception("boom"),
        ):
            result = n2_investigate(state)
        assert len(result["errors"]) > 0
