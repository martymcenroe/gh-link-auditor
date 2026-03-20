"""Tests for N4 Human Review node.

See LLD #22 §10.0 T140/T150/T240/T250: HITL routing and input.
Updated in Issue #101 for exit/skip options.
"""

from __future__ import annotations

from unittest.mock import patch

from gh_link_auditor.pipeline.nodes.n4_human_review import (
    _EXIT,
    _SKIP,
    format_verdict_for_review,
    n4_human_review,
    prompt_user_approval,
)
from gh_link_auditor.pipeline.state import (
    DeadLink,
    ReplacementCandidate,
    Verdict,
    create_initial_state,
)


def _make_verdict(
    confidence: float = 0.5,
    approved: bool | None = None,
    url: str = "https://example.com/broken",
    replacement: str | None = "https://example.com/new",
) -> Verdict:
    dl = DeadLink(
        url=url,
        source_file="README.md",
        line_number=10,
        link_text="broken",
        http_status=404,
        error_type="http_error",
    )
    candidate = None
    if replacement:
        candidate = ReplacementCandidate(
            url=replacement,
            source="redirect",
            title="New Page",
            snippet=None,
        )
    return Verdict(
        dead_link=dl,
        candidate=candidate,
        confidence=confidence,
        reasoning="test verdict",
        approved=approved,
    )


class TestFormatVerdictForReview:
    """Tests for format_verdict_for_review()."""

    def test_contains_dead_url(self) -> None:
        verdict = _make_verdict()
        output = format_verdict_for_review(verdict)
        assert "https://example.com/broken" in output

    def test_contains_replacement_url(self) -> None:
        verdict = _make_verdict(replacement="https://example.com/new")
        output = format_verdict_for_review(verdict)
        assert "https://example.com/new" in output

    def test_contains_confidence(self) -> None:
        verdict = _make_verdict(confidence=0.65)
        output = format_verdict_for_review(verdict)
        assert "0.65" in output or "65" in output

    def test_handles_no_candidate(self) -> None:
        verdict = _make_verdict(replacement=None)
        output = format_verdict_for_review(verdict)
        assert "no candidate" in output.lower() or "none" in output.lower()

    def test_contains_source_file(self) -> None:
        verdict = _make_verdict()
        output = format_verdict_for_review(verdict)
        assert "README.md" in output


class TestPromptUserApproval:
    """Tests for prompt_user_approval()."""

    def test_approve_with_y(self) -> None:
        verdict = _make_verdict()
        with patch("builtins.input", return_value="y"):
            result = prompt_user_approval(verdict)
        assert result is True

    def test_reject_with_n(self) -> None:
        verdict = _make_verdict()
        with patch("builtins.input", return_value="n"):
            result = prompt_user_approval(verdict)
        assert result is False

    def test_approve_with_yes(self) -> None:
        verdict = _make_verdict()
        with patch("builtins.input", return_value="yes"):
            result = prompt_user_approval(verdict)
        assert result is True

    def test_reject_with_no(self) -> None:
        verdict = _make_verdict()
        with patch("builtins.input", return_value="no"):
            result = prompt_user_approval(verdict)
        assert result is False

    def test_default_reject_on_empty(self) -> None:
        verdict = _make_verdict()
        with patch("builtins.input", return_value=""):
            result = prompt_user_approval(verdict)
        assert result is False

    def test_skip_with_s(self) -> None:
        verdict = _make_verdict()
        with patch("builtins.input", return_value="s"):
            result = prompt_user_approval(verdict)
        assert result is _SKIP

    def test_skip_with_skip(self) -> None:
        verdict = _make_verdict()
        with patch("builtins.input", return_value="skip"):
            result = prompt_user_approval(verdict)
        assert result is _SKIP

    def test_exit_with_x(self) -> None:
        verdict = _make_verdict()
        with patch("builtins.input", return_value="x"):
            result = prompt_user_approval(verdict)
        assert result is _EXIT

    def test_exit_with_exit(self) -> None:
        verdict = _make_verdict()
        with patch("builtins.input", return_value="exit"):
            result = prompt_user_approval(verdict)
        assert result is _EXIT

    def test_exit_with_q(self) -> None:
        verdict = _make_verdict()
        with patch("builtins.input", return_value="q"):
            result = prompt_user_approval(verdict)
        assert result is _EXIT

    def test_approve_with_a(self) -> None:
        verdict = _make_verdict()
        with patch("builtins.input", return_value="a"):
            result = prompt_user_approval(verdict)
        assert result is True

    def test_approve_with_approve(self) -> None:
        verdict = _make_verdict()
        with patch("builtins.input", return_value="approve"):
            result = prompt_user_approval(verdict)
        assert result is True

    def test_reject_with_r(self) -> None:
        verdict = _make_verdict()
        with patch("builtins.input", return_value="r"):
            result = prompt_user_approval(verdict)
        assert result is False

    def test_reject_with_reject(self) -> None:
        verdict = _make_verdict()
        with patch("builtins.input", return_value="reject"):
            result = prompt_user_approval(verdict)
        assert result is False

    def test_ctrl_c_propagates(self) -> None:
        """Ctrl+C should propagate as KeyboardInterrupt to abort pipeline."""
        verdict = _make_verdict()
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            try:
                prompt_user_approval(verdict)
                assert False, "Should have raised KeyboardInterrupt"
            except KeyboardInterrupt:
                pass  # Expected


class TestN4HumanReview:
    """Tests for n4_human_review() node function."""

    def test_routes_low_confidence_to_review(self) -> None:
        state = create_initial_state(target="t", confidence_threshold=0.8)
        state["verdicts"] = [_make_verdict(confidence=0.5)]
        with patch(
            "gh_link_auditor.pipeline.nodes.n4_human_review.prompt_user_approval",
            return_value=True,
        ):
            result = n4_human_review(state)
        assert len(result["reviewed_verdicts"]) == 1
        assert result["reviewed_verdicts"][0]["approved"] is True

    def test_skips_high_confidence(self) -> None:
        state = create_initial_state(target="t", confidence_threshold=0.8)
        state["verdicts"] = [_make_verdict(confidence=0.95)]
        result = n4_human_review(state)
        assert len(result["reviewed_verdicts"]) == 1
        assert result["reviewed_verdicts"][0]["approved"] is True

    def test_mixed_confidence(self) -> None:
        state = create_initial_state(target="t", confidence_threshold=0.8)
        state["verdicts"] = [
            _make_verdict(confidence=0.95, url="https://a.com"),
            _make_verdict(confidence=0.3, url="https://b.com"),
        ]
        with patch(
            "gh_link_auditor.pipeline.nodes.n4_human_review.prompt_user_approval",
            return_value=False,
        ):
            result = n4_human_review(state)
        assert len(result["reviewed_verdicts"]) == 2
        high = [v for v in result["reviewed_verdicts"] if v["dead_link"]["url"] == "https://a.com"]
        assert high[0]["approved"] is True
        low = [v for v in result["reviewed_verdicts"] if v["dead_link"]["url"] == "https://b.com"]
        assert low[0]["approved"] is False

    def test_skipped_in_dry_run(self) -> None:
        state = create_initial_state(target="t", dry_run=True)
        state["verdicts"] = [_make_verdict(confidence=0.5)]
        result = n4_human_review(state)
        assert len(result["reviewed_verdicts"]) == len(state["verdicts"])

    def test_empty_verdicts(self) -> None:
        state = create_initial_state(target="t")
        state["verdicts"] = []
        result = n4_human_review(state)
        assert result["reviewed_verdicts"] == []

    def test_exit_rejects_remaining(self) -> None:
        """Exit should reject current and all remaining verdicts."""
        state = create_initial_state(target="t", confidence_threshold=0.8)
        state["verdicts"] = [
            _make_verdict(confidence=0.3, url="https://a.com"),
            _make_verdict(confidence=0.3, url="https://b.com"),
            _make_verdict(confidence=0.3, url="https://c.com"),
        ]
        with patch(
            "gh_link_auditor.pipeline.nodes.n4_human_review.prompt_user_approval",
            return_value=_EXIT,
        ):
            result = n4_human_review(state)
        assert len(result["reviewed_verdicts"]) == 3
        assert all(v["approved"] is False for v in result["reviewed_verdicts"])

    def test_skip_rejects_one(self) -> None:
        """Skip should reject one verdict, continue to next."""
        state = create_initial_state(target="t", confidence_threshold=0.8)
        state["verdicts"] = [
            _make_verdict(confidence=0.3, url="https://a.com"),
            _make_verdict(confidence=0.3, url="https://b.com"),
        ]
        # First call: skip, second call: approve
        with patch(
            "gh_link_auditor.pipeline.nodes.n4_human_review.prompt_user_approval",
            side_effect=[_SKIP, True],
        ):
            result = n4_human_review(state)
        a = [v for v in result["reviewed_verdicts"] if v["dead_link"]["url"] == "https://a.com"]
        b = [v for v in result["reviewed_verdicts"] if v["dead_link"]["url"] == "https://b.com"]
        assert a[0]["approved"] is False
        assert b[0]["approved"] is True

    def test_exit_after_approve_preserves_earlier(self) -> None:
        """Approve first, exit second — first stays approved."""
        state = create_initial_state(target="t", confidence_threshold=0.8)
        state["verdicts"] = [
            _make_verdict(confidence=0.3, url="https://a.com"),
            _make_verdict(confidence=0.3, url="https://b.com"),
            _make_verdict(confidence=0.3, url="https://c.com"),
        ]
        with patch(
            "gh_link_auditor.pipeline.nodes.n4_human_review.prompt_user_approval",
            side_effect=[True, _EXIT],
        ):
            result = n4_human_review(state)
        a = [v for v in result["reviewed_verdicts"] if v["dead_link"]["url"] == "https://a.com"]
        b = [v for v in result["reviewed_verdicts"] if v["dead_link"]["url"] == "https://b.com"]
        c = [v for v in result["reviewed_verdicts"] if v["dead_link"]["url"] == "https://c.com"]
        assert a[0]["approved"] is True
        assert b[0]["approved"] is False
        assert c[0]["approved"] is False

    def test_review_aborted_set_on_exit(self) -> None:
        """Exit sets review_aborted flag in state."""
        state = create_initial_state(target="t", confidence_threshold=0.8)
        state["verdicts"] = [_make_verdict(confidence=0.3)]
        with patch(
            "gh_link_auditor.pipeline.nodes.n4_human_review.prompt_user_approval",
            return_value=_EXIT,
        ):
            result = n4_human_review(state)
        assert result["review_aborted"] is True

    def test_review_aborted_false_without_exit(self) -> None:
        """Normal completion does not set review_aborted."""
        state = create_initial_state(target="t", confidence_threshold=0.8)
        state["verdicts"] = [_make_verdict(confidence=0.3)]
        with patch(
            "gh_link_auditor.pipeline.nodes.n4_human_review.prompt_user_approval",
            return_value=True,
        ):
            result = n4_human_review(state)
        assert result["review_aborted"] is False

    def test_review_aborted_false_on_auto_approve(self) -> None:
        """High-confidence auto-approve does not set review_aborted."""
        state = create_initial_state(target="t", confidence_threshold=0.8)
        state["verdicts"] = [_make_verdict(confidence=0.95)]
        result = n4_human_review(state)
        assert result["review_aborted"] is False

    def test_review_aborted_false_in_dry_run(self) -> None:
        """Dry run does not set review_aborted."""
        state = create_initial_state(target="t", dry_run=True)
        state["verdicts"] = [_make_verdict(confidence=0.3)]
        result = n4_human_review(state)
        assert result["review_aborted"] is False
