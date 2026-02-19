"""N4 Human Review node.

Terminal-based human-in-the-loop review for low-confidence verdicts.

See LLD #22 §2.4 for n4_human_review specification.
"""

from __future__ import annotations

from gh_link_auditor.pipeline.state import PipelineState, Verdict


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
        f"Dead URL: {dead_link['url']}",
        f"Source:   {dead_link['source_file']}:{dead_link['line_number']}",
        f"Confidence: {confidence}",
    ]

    if candidate:
        lines.append(f"Proposed replacement: {candidate['url']}")
        lines.append(f"Found via: {candidate['source']}")
    else:
        lines.append("Proposed replacement: None (no candidate found)")

    if verdict.get("reasoning"):
        lines.append(f"Reasoning: {verdict['reasoning']}")

    return "\n".join(lines)


def prompt_user_approval(verdict: Verdict) -> bool:
    """Interactive prompt for user to approve/reject a verdict.

    Args:
        verdict: Verdict to review.

    Returns:
        True if approved, False if rejected.
    """
    try:
        response = input("[y]es / [n]o: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    return response in ("y", "yes")


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

    for verdict in verdicts:
        confidence = verdict.get("confidence", 0)

        if dry_run or confidence >= threshold:
            # Auto-approve high confidence or skip review in dry run
            updated = dict(verdict)
            updated["approved"] = True
            reviewed.append(updated)  # type: ignore[arg-type]
        else:
            # Present to user for review
            print(format_verdict_for_review(verdict))
            approved = prompt_user_approval(verdict)
            updated = dict(verdict)
            updated["approved"] = approved
            reviewed.append(updated)  # type: ignore[arg-type]

    state["reviewed_verdicts"] = reviewed
    return state
