"""Tests for pipeline graph wiring.

See LLD #22 §10.0 T190/T200: Dry run, full pipeline happy path.
"""

from __future__ import annotations

from unittest.mock import patch

from gh_link_auditor.pipeline.graph import (
    _after_judge_router,
    _after_n4_router,
    _after_n5_router,
    _after_pr_preview_router,
    _pr_preview_gate,
    build_pipeline_graph,
    run_pipeline,
    should_route_to_human_review,
    should_trigger_circuit_breaker,
)
from gh_link_auditor.pipeline.state import (
    DeadLink,
    ReplacementCandidate,
    Verdict,
    create_initial_state,
)


def _make_dead_link(url: str = "https://dead.com") -> DeadLink:
    return DeadLink(
        url=url,
        source_file="README.md",
        line_number=1,
        link_text="link",
        http_status=404,
        error_type="http_error",
    )


def _make_verdict(confidence: float = 0.95) -> Verdict:
    return Verdict(
        dead_link=_make_dead_link(),
        candidate=ReplacementCandidate(
            url="https://new.com",
            source="redirect",
            title=None,
            snippet=None,
        ),
        confidence=confidence,
        reasoning="test",
        approved=None,
    )


class TestShouldTriggerCircuitBreaker:
    """Tests for should_trigger_circuit_breaker()."""

    def test_triggers_over_threshold(self) -> None:
        state = create_initial_state(target="t", max_links=5)
        state["dead_links"] = [_make_dead_link(f"https://dead{i}.com") for i in range(10)]
        assert should_trigger_circuit_breaker(state) is True

    def test_passes_under_threshold(self) -> None:
        state = create_initial_state(target="t", max_links=50)
        state["dead_links"] = [_make_dead_link()]
        assert should_trigger_circuit_breaker(state) is False

    def test_passes_empty(self) -> None:
        state = create_initial_state(target="t")
        state["dead_links"] = []
        assert should_trigger_circuit_breaker(state) is False


class TestShouldRouteToHumanReview:
    """Tests for should_route_to_human_review()."""

    def test_routes_when_low_confidence(self) -> None:
        state = create_initial_state(target="t", confidence_threshold=0.8)
        state["verdicts"] = [_make_verdict(0.5)]
        assert should_route_to_human_review(state) is True

    def test_skips_when_all_high(self) -> None:
        state = create_initial_state(target="t", confidence_threshold=0.8)
        state["verdicts"] = [_make_verdict(0.95)]
        assert should_route_to_human_review(state) is False

    def test_skips_dry_run(self) -> None:
        state = create_initial_state(target="t", dry_run=True)
        state["verdicts"] = [_make_verdict(0.5)]
        assert should_route_to_human_review(state) is False


class TestAfterJudgeRouter:
    """Tests for _after_judge_router()."""

    def test_returns_end_for_dry_run(self) -> None:
        state = create_initial_state(target="t", dry_run=True)
        state["verdicts"] = [_make_verdict(0.5)]
        result = _after_judge_router(state)
        assert result == "__end__"

    def test_returns_end_for_cost_limit(self) -> None:
        state = create_initial_state(target="t")
        state["cost_limit_reached"] = True
        state["verdicts"] = [_make_verdict()]
        result = _after_judge_router(state)
        assert result == "__end__"

    def test_routes_to_human_review(self) -> None:
        state = create_initial_state(target="t")
        state["verdicts"] = [_make_verdict()]
        result = _after_judge_router(state)
        assert result == "n4_human_review"


class TestAfterN4Router:
    """Tests for _after_n4_router() — abort check after human review."""

    def test_returns_end_when_aborted(self) -> None:
        state = create_initial_state(target="t")
        state["review_aborted"] = True
        assert _after_n4_router(state) == "__end__"

    def test_routes_to_n5_when_not_aborted(self) -> None:
        state = create_initial_state(target="t")
        state["review_aborted"] = False
        assert _after_n4_router(state) == "n5_generate_fix"

    def test_routes_to_n5_when_flag_missing(self) -> None:
        state = create_initial_state(target="t")
        assert _after_n4_router(state) == "n5_generate_fix"


class TestAfterN5Router:
    """Tests for _after_n5_router()."""

    def test_returns_end_for_dry_run(self) -> None:
        state = create_initial_state(target="t", dry_run=True)
        state["fixes"] = [{"source_file": "a.md", "original_url": "x", "replacement_url": "y", "unified_diff": "d"}]
        state["target_type"] = "url"
        assert _after_n5_router(state) == "__end__"

    def test_returns_end_for_local_target(self) -> None:
        state = create_initial_state(target="/path")
        state["target_type"] = "local"
        state["fixes"] = [{"source_file": "a.md", "original_url": "x", "replacement_url": "y", "unified_diff": "d"}]
        assert _after_n5_router(state) == "__end__"

    def test_returns_end_for_empty_fixes(self) -> None:
        state = create_initial_state(target="https://github.com/org/repo")
        state["target_type"] = "url"
        state["fixes"] = []
        assert _after_n5_router(state) == "__end__"

    def test_routes_to_n6_for_url_with_fixes(self) -> None:
        state = create_initial_state(target="https://github.com/org/repo")
        state["target_type"] = "url"
        state["fixes"] = [{"source_file": "a.md", "original_url": "x", "replacement_url": "y", "unified_diff": "d"}]
        assert _after_n5_router(state) == "pr_preview_gate"


class TestPrPreviewGate:
    """Tests for _pr_preview_gate() and _after_pr_preview_router()."""

    def test_no_fixes_sets_not_approved(self) -> None:
        state = create_initial_state(target="t")
        state["fixes"] = []
        result = _pr_preview_gate(state)
        assert result["pr_preview_approved"] is False

    def test_user_submits(self) -> None:
        state = create_initial_state(target="t")
        state["fixes"] = [{"source_file": "a.md", "original_url": "x", "replacement_url": "y", "unified_diff": "d"}]
        with patch("builtins.input", return_value="s"):
            result = _pr_preview_gate(state)
        assert result["pr_preview_approved"] is True

    def test_user_exits(self) -> None:
        state = create_initial_state(target="t")
        state["fixes"] = [{"source_file": "a.md", "original_url": "x", "replacement_url": "y", "unified_diff": "d"}]
        with patch("builtins.input", return_value="x"):
            result = _pr_preview_gate(state)
        assert result["pr_preview_approved"] is False

    def test_user_reviews_then_submits(self) -> None:
        state = create_initial_state(target="t")
        state["fixes"] = [{"source_file": "a.md", "original_url": "x", "replacement_url": "y", "unified_diff": "d"}]
        with patch("builtins.input", side_effect=["r", "s"]):
            result = _pr_preview_gate(state)
        assert result["pr_preview_approved"] is True

    def test_user_invalid_then_submits(self) -> None:
        state = create_initial_state(target="t")
        state["fixes"] = [{"source_file": "a.md", "original_url": "x", "replacement_url": "y", "unified_diff": "d"}]
        with patch("builtins.input", side_effect=["garbage", "s"]):
            result = _pr_preview_gate(state)
        assert result["pr_preview_approved"] is True

    def test_preview_shows_pr_title_and_body(self, capsys) -> None:
        state = create_initial_state(target="t")
        state["fixes"] = [
            {
                "source_file": "README.md",
                "original_url": "https://old.com",
                "replacement_url": "https://new.com",
                "unified_diff": "d",
            }
        ]
        with patch("builtins.input", return_value="s"):
            _pr_preview_gate(state)
        captured = capsys.readouterr()
        assert "Title:" in captured.out
        assert "Body:" in captured.out
        assert "README.md" in captured.out

    def test_router_approved(self) -> None:
        state = create_initial_state(target="t")
        state["pr_preview_approved"] = True
        assert _after_pr_preview_router(state) == "n6_submit_pr"

    def test_router_not_approved(self) -> None:
        state = create_initial_state(target="t")
        state["pr_preview_approved"] = False
        assert _after_pr_preview_router(state) == "__end__"

    def test_router_missing_flag(self) -> None:
        state = create_initial_state(target="t")
        assert _after_pr_preview_router(state) == "__end__"


class TestBuildPipelineGraph:
    """Tests for build_pipeline_graph()."""

    def test_returns_compiled_graph(self) -> None:
        graph = build_pipeline_graph()
        assert graph is not None

    def test_graph_has_nodes(self) -> None:
        graph = build_pipeline_graph()
        # LangGraph compiled graph should have node info
        assert hasattr(graph, "invoke") or hasattr(graph, "stream")


class TestRunPipeline:
    """Tests for run_pipeline()."""

    def test_happy_path_with_mocks(self, tmp_path) -> None:
        (tmp_path / "README.md").write_text("Check [link](https://old.example.com/page)\n")
        state = create_initial_state(target=str(tmp_path))

        with (
            patch(
                "gh_link_auditor.pipeline.nodes.n1_scan.run_link_scan",
                return_value=[_make_dead_link()],
            ),
            patch(
                "gh_link_auditor.pipeline.nodes.n2_investigate.investigate_dead_link",
                return_value=[
                    {
                        "url": "https://new.com",
                        "source": "redirect",
                        "title": None,
                        "snippet": None,
                    }
                ],
            ),
            patch(
                "gh_link_auditor.pipeline.nodes.n3_judge.judge_candidates",
                return_value={
                    "dead_link": _make_dead_link(),
                    "candidate": {"url": "https://new.com", "source": "redirect", "title": None, "snippet": None},
                    "confidence": 0.95,
                    "reasoning": "good",
                    "approved": None,
                },
            ),
        ):
            result = run_pipeline(state)
        assert result["scan_complete"] is True

    def test_dry_run_skips_n4_n5(self, tmp_path) -> None:
        state = create_initial_state(target=str(tmp_path), dry_run=True)
        state["dead_links"] = []
        with patch(
            "gh_link_auditor.pipeline.nodes.n1_scan.run_link_scan",
            return_value=[],
        ):
            result = run_pipeline(state)
        assert result.get("fixes", []) == []

    def test_circuit_breaker_halts(self, tmp_path) -> None:
        state = create_initial_state(target=str(tmp_path), max_links=1)
        dead_links = [_make_dead_link(f"https://dead{i}.com") for i in range(5)]
        with patch(
            "gh_link_auditor.pipeline.nodes.n1_scan.run_link_scan",
            return_value=dead_links,
        ):
            result = run_pipeline(state)
        assert result["circuit_breaker_triggered"] is True
