"""Data contract integration tests.

Validates that data flows correctly between pipeline nodes by running
real node functions with controlled inputs and checking output shapes.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from gh_link_auditor.pipeline.nodes.n3_judge import n3_judge
from gh_link_auditor.pipeline.nodes.n4_human_review import n4_human_review
from gh_link_auditor.pipeline.nodes.n5_generate_fix import generate_unified_diff
from gh_link_auditor.pipeline.state import (
    DeadLink,
    ReplacementCandidate,
    Verdict,
    create_initial_state,
    load_state,
    persist_state,
)


def _make_dead_link(url: str = "https://dead.example.com/page") -> DeadLink:
    return DeadLink(
        url=url,
        source_file="README.md",
        line_number=5,
        link_text="link text",
        http_status=404,
        error_type="http_error",
    )


def _make_candidate(url: str = "https://new.example.com/page") -> ReplacementCandidate:
    return ReplacementCandidate(
        url=url,
        source="redirect_chain",
        title="New Page",
        snippet=None,
    )


@pytest.mark.integration
class TestDataContracts:
    """Cross-node data shape validation."""

    def test_n2_output_feeds_n3(self) -> None:
        """State with candidates passes to N3, produces typed Verdicts."""
        state = create_initial_state(target="t")
        dead_link = _make_dead_link()
        state["dead_links"] = [dead_link]
        state["candidates"] = {
            dead_link["url"]: [_make_candidate()],
        }

        with patch(
            "gh_link_auditor.pipeline.nodes.n3_judge._score_candidates",
            return_value=Verdict(
                dead_link=dead_link,
                candidate=_make_candidate(),
                confidence=0.95,
                reasoning="redirect match",
                approved=None,
            ),
        ):
            result = n3_judge(state)

        assert "verdicts" in result
        assert len(result["verdicts"]) >= 1
        v = result["verdicts"][0]
        assert "confidence" in v
        assert "dead_link" in v

    def test_n3_output_feeds_n4(self) -> None:
        """Verdicts pass through N4 auto-approve for high confidence."""
        state = create_initial_state(target="t")
        dead_link = _make_dead_link()
        state["verdicts"] = [
            Verdict(
                dead_link=dead_link,
                candidate=_make_candidate(),
                confidence=0.99,
                reasoning="perfect match",
                approved=None,
            ),
        ]

        # N4 auto-approves verdicts above threshold
        result = n4_human_review(state)
        assert "reviewed_verdicts" in result
        assert len(result["reviewed_verdicts"]) >= 1
        # High-confidence should be auto-approved
        assert result["reviewed_verdicts"][0]["approved"] is True

    def test_n5_produces_parseable_diffs(self, tmp_path: Path) -> None:
        """N5 output diffs are valid unified diff format."""
        readme = tmp_path / "README.md"
        readme.write_text("Visit https://dead.example.com/page for info.\n")

        diff = generate_unified_diff(
            str(readme),
            "https://dead.example.com/page",
            "https://new.example.com/page",
        )

        assert diff != ""
        assert "---" in diff
        assert "+++" in diff
        assert "-Visit https://dead.example.com/page" in diff
        assert "+Visit https://new.example.com/page" in diff

    def test_pipeline_state_serialization_roundtrip(self, tmp_path: Path) -> None:
        """persist_state + load_state preserves all fields."""
        db_path = str(tmp_path / "state.db")
        state = create_initial_state(target="https://github.com/org/repo", db_path=db_path)
        state["dead_links"] = [_make_dead_link()]
        state["scan_complete"] = True

        persist_state(state, "n1_scan")

        loaded = load_state(state["run_id"], db_path)
        assert loaded is not None
        assert loaded["target"] == "https://github.com/org/repo"
        assert loaded["scan_complete"] is True
        assert len(loaded["dead_links"]) == 1
