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


def _after_n4_router(state: PipelineState) -> str:
    """Route after N4: abort pipeline if user chose exit."""
    if state.get("review_aborted", False):
        return END
    return "n5_generate_fix"


def _get_repo_trust_level(state: PipelineState) -> str:
    """Look up the trust level for the current target repo.

    Returns "new" if no trust record exists or the target is local.

    Args:
        state: Current pipeline state.

    Returns:
        Trust level string.
    """
    if state.get("target_type") != "url":
        return "new"

    owner = state.get("repo_owner", "")
    name = state.get("repo_name_short", "")
    if not owner or not name:
        return "new"

    repo_full_name = f"{owner}/{name}"

    try:
        from gh_link_auditor.unified_db import UnifiedDatabase

        db_path = state.get("db_path", "")
        if not db_path:
            return "new"
        db = UnifiedDatabase(db_path)
        try:
            trust = db.get_repo_trust(repo_full_name)
            if trust is None:
                return "new"
            return trust["trust_level"]
        finally:
            db.close()
    except Exception:
        logger.debug("Could not look up trust level for %s", repo_full_name)
        return "new"


def _filter_fixes_by_trust(
    fixes: list[dict],
    verdicts: list[dict],
    candidates: dict[str, list[dict]],
    trust_level: str,
) -> tuple[list[dict], int]:
    """Filter fixes based on repo trust level.

    For repos at "new" or "tier1_pending", tier 2 fixes are excluded.

    Args:
        fixes: List of FixPatch dicts.
        verdicts: List of Verdict dicts (for looking up candidate tiers).
        candidates: Candidates dict keyed by dead URL.
        trust_level: Current repo trust level.

    Returns:
        Tuple of (filtered fixes, count of excluded tier 2 fixes).
    """
    if trust_level not in ("new", "tier1_pending"):
        return fixes, 0

    # Build a set of URLs whose best candidate is tier 2
    tier2_urls: set[str] = set()
    for url, cands in candidates.items():
        for c in cands:
            if c.get("tier", 1) == 2:
                tier2_urls.add(url)

    # Also check verdicts — the chosen candidate's source
    for v in verdicts:
        cand = v.get("candidate")
        if cand and cand.get("tier", 1) == 2:
            dl = v.get("dead_link", {})
            tier2_urls.add(dl.get("url", ""))

    filtered = []
    excluded = 0
    for fix in fixes:
        if fix.get("original_url", "") in tier2_urls:
            excluded += 1
        else:
            filtered.append(fix)

    return filtered, excluded


def _pr_preview_gate(state: PipelineState) -> PipelineState:
    """Show PR preview and ask user to confirm before submission.

    Checks repo trust level and filters out tier 2 fixes for untrusted repos.
    Displays the fixes that will be submitted and prompts for confirmation.
    Sets pr_preview_approved in state.
    """
    fixes = state.get("fixes", [])
    if not fixes:
        state["pr_preview_approved"] = False
        return state

    # Look up trust level and filter tier 2 fixes for untrusted repos
    trust_level = _get_repo_trust_level(state)
    state["repo_trust_level"] = trust_level

    verdicts = state.get("verdicts", [])
    candidates = state.get("candidates", {})
    fixes, excluded = _filter_fixes_by_trust(fixes, verdicts, candidates, trust_level)
    state["fixes"] = fixes
    state["tier2_fixes_excluded"] = excluded

    if not fixes:
        if excluded > 0:
            print(f"\n  All {excluded} fix(es) are tier 2 (risky) — excluded for repo at trust level '{trust_level}'.")
        state["pr_preview_approved"] = False
        return state

    from gh_link_auditor.pipeline.pr_message import (
        generate_pr_body_from_fixes,
        generate_pr_title_from_fixes,
    )

    pr_title = generate_pr_title_from_fixes(fixes)
    pr_body = generate_pr_body_from_fixes(fixes, verdicts)

    def _display_preview():
        print("\n" + "=" * 60)
        print("  PR PREVIEW")
        print("=" * 60)
        print(f"\n  Title: {pr_title}\n")
        print("  Body:")
        for line in pr_body.split("\n"):
            print(f"    {line}")
        print()
        print(f"  Fixes: {len(fixes)}")
        if excluded > 0:
            print(f"  ({excluded} tier 2 fix(es) excluded — repo trust: {trust_level})")
        print()
        for i, fix in enumerate(fixes, start=1):
            print(f"  {i}. {fix['source_file']}")
            print(f"     {fix['original_url']}")
            print(f"     -> {fix['replacement_url']}")
        print("=" * 60)

    _display_preview()

    while True:
        response = input("  [r]eview / [s]ubmit / e[x]it: ").strip().lower()
        if response in ("r", "review"):
            _display_preview()
        elif response in ("s", "submit"):
            state["pr_preview_approved"] = True
            return state
        elif response in ("x", "exit"):
            state["pr_preview_approved"] = False
            return state
        else:
            print("  Invalid option. Use [r]eview, [s]ubmit, or e[x]it.")


def _after_pr_preview_router(state: PipelineState) -> str:
    """Route after PR preview: submit or abort."""
    if state.get("pr_preview_approved", False):
        return "n6_submit_pr"
    return END


def _after_n5_router(state: PipelineState) -> str:
    """Route after N5: to PR preview, or end for dry-run/local/no-fixes."""
    if state.get("dry_run", False):
        return END

    if state.get("target_type", "local") != "url":
        return END

    fixes = state.get("fixes", [])
    if not fixes:
        return END

    return "pr_preview_gate"


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
    graph.add_node("pr_preview_gate", _pr_preview_gate)
    graph.add_node("n6_submit_pr", n6_submit_pr)

    graph.set_entry_point("n0_load_target")

    graph.add_edge("n0_load_target", "n1_scan")
    graph.add_edge("n1_scan", "circuit_breaker_check")
    graph.add_conditional_edges("circuit_breaker_check", _after_circuit_breaker_router)
    graph.add_edge("n2_investigate", "n3_judge")
    graph.add_conditional_edges("n3_judge", _after_judge_router)
    graph.add_conditional_edges("n4_human_review", _after_n4_router)
    graph.add_conditional_edges("n5_generate_fix", _after_n5_router)
    graph.add_conditional_edges("pr_preview_gate", _after_pr_preview_router)
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
