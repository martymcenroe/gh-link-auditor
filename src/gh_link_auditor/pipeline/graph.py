"""LangGraph pipeline graph wiring.

Constructs the StateGraph with all nodes and conditional edges
for the dead link resolution pipeline.

See LLD #22 §2.4 for graph specification.
"""

from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph

from gh_link_auditor.pipeline.circuit_breaker import CircuitBreaker
from gh_link_auditor.pipeline.nodes.n0_load_target import n0_load_target
from gh_link_auditor.pipeline.nodes.n1_scan import n1_scan
from gh_link_auditor.pipeline.nodes.n2_investigate import n2_investigate
from gh_link_auditor.pipeline.nodes.n3_judge import n3_judge
from gh_link_auditor.pipeline.nodes.n4_human_review import n4_human_review
from gh_link_auditor.pipeline.nodes.n5_generate_fix import n5_generate_fix
from gh_link_auditor.pipeline.nodes.n6_submit_pr import n6_submit_pr
from gh_link_auditor.pipeline.state import PipelineState

logger = logging.getLogger(__name__)


def should_trigger_circuit_breaker(state: PipelineState) -> bool:
    """Check if dead link count exceeds max_links threshold.

    Args:
        state: Current pipeline state.

    Returns:
        True if circuit breaker should trigger.
    """
    max_links = state.get("max_links", 50)
    dead_links = state.get("dead_links", [])
    cb = CircuitBreaker(max_links=max_links)
    triggered, _ = cb.check_link_count(dead_links)
    return triggered


def should_route_to_human_review(state: PipelineState) -> bool:
    """Check if any verdicts have confidence below threshold.

    Args:
        state: Current pipeline state.

    Returns:
        True if human review is needed.
    """
    if state.get("dry_run", False):
        return False

    threshold = state.get("confidence_threshold", 0.8)
    verdicts = state.get("verdicts", [])

    return any(v.get("confidence", 0) < threshold for v in verdicts)


def _circuit_breaker_check(state: PipelineState) -> PipelineState:
    """Check circuit breaker and set flag in state.

    This is a node (not a router) so it can modify state.
    """
    if should_trigger_circuit_breaker(state):
        state["circuit_breaker_triggered"] = True
    return state


def _after_circuit_breaker_router(state: PipelineState) -> str:
    """Route after circuit breaker check."""
    dead_links = state.get("dead_links", [])

    if not dead_links:
        return END

    if state.get("circuit_breaker_triggered", False):
        return END

    return "n2_investigate"


def _after_judge_router(state: PipelineState) -> str:
    """Route after N3 judge based on confidence and dry-run."""
    if state.get("dry_run", False):
        return END

    if state.get("cost_limit_reached", False):
        return END

    # Always go to N4 — it handles auto-approval for high confidence
    return "n4_human_review"


def _after_n5_router(state: PipelineState) -> str:
    """Route after N5: submit PR or end.

    Skips N6 for dry-run, local targets, or when no fixes were generated.
    """
    if state.get("dry_run", False):
        return END

    if state.get("target_type", "local") != "url":
        return END

    fixes = state.get("fixes", [])
    if not fixes:
        return END

    return "n6_submit_pr"


def build_pipeline_graph():
    """Construct the LangGraph StateGraph with all nodes and edges.

    Returns:
        Compiled StateGraph ready for invocation.
    """
    graph = StateGraph(PipelineState)

    graph.add_node("n0_load_target", n0_load_target)
    graph.add_node("n1_scan", n1_scan)
    graph.add_node("circuit_breaker_check", _circuit_breaker_check)
    graph.add_node("n2_investigate", n2_investigate)
    graph.add_node("n3_judge", n3_judge)
    graph.add_node("n4_human_review", n4_human_review)
    graph.add_node("n5_generate_fix", n5_generate_fix)
    graph.add_node("n6_submit_pr", n6_submit_pr)

    graph.set_entry_point("n0_load_target")

    graph.add_edge("n0_load_target", "n1_scan")
    graph.add_edge("n1_scan", "circuit_breaker_check")
    graph.add_conditional_edges("circuit_breaker_check", _after_circuit_breaker_router)
    graph.add_edge("n2_investigate", "n3_judge")
    graph.add_conditional_edges("n3_judge", _after_judge_router)
    graph.add_edge("n4_human_review", "n5_generate_fix")
    graph.add_conditional_edges("n5_generate_fix", _after_n5_router)
    graph.add_edge("n6_submit_pr", END)

    return graph.compile()


def run_pipeline(state: PipelineState) -> PipelineState:
    """Execute the full pipeline and return final state.

    Args:
        state: Initial pipeline state.

    Returns:
        Final PipelineState after all nodes have executed.
    """
    graph = build_pipeline_graph()
    result = graph.invoke(state)
    return result
