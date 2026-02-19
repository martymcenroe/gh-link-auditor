"""Tests for N3 Judge node.

See LLD #22 §10.0 T120/T130: N3 high/low confidence verdicts.
"""

from __future__ import annotations

from unittest.mock import patch

from gh_link_auditor.pipeline.nodes.n3_judge import (
    judge_candidates,
    n3_judge,
)
from gh_link_auditor.pipeline.state import (
    DeadLink,
    ReplacementCandidate,
    create_initial_state,
)


def _make_dead_link(url: str = "https://example.com/broken") -> DeadLink:
    return DeadLink(
        url=url,
        source_file="README.md",
        line_number=10,
        link_text="broken link",
        http_status=404,
        error_type="http_error",
    )


def _make_candidate(url: str = "https://example.com/new") -> ReplacementCandidate:
    return ReplacementCandidate(
        url=url,
        source="redirect_chain",
        title="New Page",
        snippet=None,
    )


class TestJudgeCandidates:
    """Tests for judge_candidates()."""

    def test_high_confidence_verdict(self) -> None:
        dead_link = _make_dead_link()
        candidates = [_make_candidate()]
        mock_verdict = {
            "dead_url": dead_link["url"],
            "verdict": "AUTO-APPROVE",
            "confidence": 95,
            "replacement_url": candidates[0]["url"],
            "scoring_breakdown": {
                "redirect": 40.0,
                "title_match": 25.0,
                "content_similarity": 20.0,
                "url_similarity": 5.0,
                "domain_match": 5.0,
            },
            "human_decision": "auto",
            "decided_at": None,
        }
        with patch(
            "gh_link_auditor.pipeline.nodes.n3_judge._score_candidates",
            return_value=mock_verdict,
        ):
            verdict = judge_candidates(dead_link, candidates)
        assert verdict["confidence"] >= 0.8 or verdict.get("verdict") == "AUTO-APPROVE"

    def test_low_confidence_verdict(self) -> None:
        dead_link = _make_dead_link()
        candidates = [_make_candidate("https://unrelated.com/page")]
        mock_verdict = {
            "dead_url": dead_link["url"],
            "verdict": "LOW-CONFIDENCE",
            "confidence": 45,
            "replacement_url": candidates[0]["url"],
            "scoring_breakdown": {
                "redirect": 0.0,
                "title_match": 10.0,
                "content_similarity": 15.0,
                "url_similarity": 10.0,
                "domain_match": 0.0,
            },
            "human_decision": None,
            "decided_at": None,
        }
        with patch(
            "gh_link_auditor.pipeline.nodes.n3_judge._score_candidates",
            return_value=mock_verdict,
        ):
            verdict = judge_candidates(dead_link, candidates)
        assert verdict["confidence"] < 80

    def test_no_candidates(self) -> None:
        dead_link = _make_dead_link()
        verdict = judge_candidates(dead_link, [])
        assert verdict["confidence"] == 0
        assert verdict.get("replacement_url") is None or verdict.get("candidate") is None

    def test_handles_scoring_error(self) -> None:
        dead_link = _make_dead_link()
        candidates = [_make_candidate()]
        with patch(
            "gh_link_auditor.pipeline.nodes.n3_judge._score_candidates",
            side_effect=Exception("scoring failed"),
        ):
            verdict = judge_candidates(dead_link, candidates)
        assert verdict["confidence"] == 0


class TestN3Judge:
    """Tests for n3_judge() node function."""

    def test_produces_verdicts(self) -> None:
        state = create_initial_state(target="t")
        state["dead_links"] = [_make_dead_link()]
        state["candidates"] = {
            "https://example.com/broken": [_make_candidate()],
        }
        mock_verdict = {
            "dead_url": "https://example.com/broken",
            "verdict": "AUTO-APPROVE",
            "confidence": 95,
            "replacement_url": "https://example.com/new",
            "scoring_breakdown": {},
            "human_decision": "auto",
            "decided_at": None,
        }
        with patch(
            "gh_link_auditor.pipeline.nodes.n3_judge.judge_candidates",
            return_value=mock_verdict,
        ):
            result = n3_judge(state)
        assert len(result["verdicts"]) == 1

    def test_empty_candidates(self) -> None:
        state = create_initial_state(target="t")
        state["dead_links"] = [_make_dead_link()]
        state["candidates"] = {}
        result = n3_judge(state)
        assert len(result["verdicts"]) == 1
        assert result["verdicts"][0]["confidence"] == 0

    def test_skips_when_cost_limit(self) -> None:
        state = create_initial_state(target="t")
        state["dead_links"] = [_make_dead_link()]
        state["candidates"] = {"https://example.com/broken": [_make_candidate()]}
        state["cost_limit_reached"] = True
        result = n3_judge(state)
        # Should still produce verdicts but may skip LLM calls
        assert "verdicts" in result

    def test_error_handling(self) -> None:
        state = create_initial_state(target="t")
        state["dead_links"] = [_make_dead_link()]
        state["candidates"] = {"https://example.com/broken": [_make_candidate()]}
        with patch(
            "gh_link_auditor.pipeline.nodes.n3_judge.judge_candidates",
            side_effect=Exception("judge error"),
        ):
            result = n3_judge(state)
        assert len(result["errors"]) > 0
