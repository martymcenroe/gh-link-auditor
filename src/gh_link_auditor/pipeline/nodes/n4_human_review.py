"""N4 Human Review node.

Terminal-based human-in-the-loop review for low-confidence verdicts.

See LLD #22 §2.4 for n4_human_review specification.
"""

from __future__ import annotations

from gh_link_auditor.pipeline.state import PipelineState, Verdict

# Sentinel to signal "exit review, reject all remaining"
_EXIT = "exit"
_SKIP = "skip"


def format_verdict_for_review(verdict: Verdict) -> str:
    """Format a verdict for terminal display.

    Args:
        verdict: Verdict to format.

    Returns:
        Formatted string for review.
    """
    dead_link = verdict["dead_link"]
    candidate = verdict.get("candidate")
    confidence = verdict.get("confidence", 0)

    lines = [
        "",
        "-" * 50,
        f"  Dead URL:  {dead_link['url']}",
        f"  File:      {dead_link['source_file']}:{dead_link['line_number']}",
        f"  Confidence: {confidence:.0%}",
    ]

    if candidate:
        lines.append(f"  Replace with: {candidate['url']}")
        lines.append(f"  Found via:    {candidate['source']}")
    else:
        lines.append("  Replace with: (no candidate)")

    if verdict.get("reasoning"):
        lines.append(f"  Reasoning:    {verdict['reasoning']}")

    lines.append("-" * 50)
    return "\n".join(lines)


def prompt_user_approval(verdict: Verdict) -> bool | str:
    """Interactive prompt for user to approve/reject/skip/exit.

    Args:
        verdict: Verdict to review.

    Returns:
        True if approved, False if rejected, "skip" to skip, "exit" to abort.

    Raises:
        KeyboardInterrupt: If user presses Ctrl+C (aborts pipeline).
    """
    response = input("[a]pprove / [r]eject / [s]kip / e[x]it: ").strip().lower()

    if response in ("a", "approve", "y", "yes"):
        return True
    if response in ("s", "skip"):
        return _SKIP
    if response in ("x", "exit", "q", "quit"):
        return _EXIT

    # "r", "reject", "n", "no", or anything else → reject
    return False


def n4_human_review(state: PipelineState) -> PipelineState:
    """N4 node: Terminal-based human review for low-confidence verdicts.

    High-confidence verdicts are auto-approved. Low-confidence verdicts
    are presented to the user for approval. Skipped entirely in dry-run mode.

    Args:
        state: Current pipeline state.

    Returns:
        Updated PipelineState with reviewed_verdicts populated.
    """
    verdicts = state.get("verdicts", [])
    threshold = state.get("confidence_threshold", 0.8)
    dry_run = state.get("dry_run", False)

    reviewed: list[Verdict] = []
    exit_review = False

    for verdict in verdicts:
        confidence = verdict.get("confidence", 0)

        if dry_run or confidence >= threshold:
            # Auto-approve high confidence or skip review in dry run
            updated = dict(verdict)
            updated["approved"] = True
            reviewed.append(updated)  # type: ignore[arg-type]
        elif exit_review:
            # User chose exit — reject all remaining
            updated = dict(verdict)
            updated["approved"] = False
            reviewed.append(updated)  # type: ignore[arg-type]
        else:
            # Present to user for review
            print(format_verdict_for_review(verdict))
            result = prompt_user_approval(verdict)

            if result is _EXIT:
                exit_review = True
                updated = dict(verdict)
                updated["approved"] = False
                reviewed.append(updated)  # type: ignore[arg-type]
            elif result is _SKIP:
                updated = dict(verdict)
                updated["approved"] = False
                reviewed.append(updated)  # type: ignore[arg-type]
            else:
                updated = dict(verdict)
                updated["approved"] = bool(result)
                reviewed.append(updated)  # type: ignore[arg-type]

    state["reviewed_verdicts"] = reviewed
    state["review_aborted"] = exit_review
    return state
