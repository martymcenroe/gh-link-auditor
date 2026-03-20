"""N4 Human Review node.

Terminal-based human-in-the-loop review for low-confidence verdicts.

See LLD #22 section 2.4 for n4_human_review specification.
Updated in #148 with snooze key binding.
"""

from __future__ import annotations

import logging

from gh_link_auditor.pipeline.state import PipelineState, Verdict

logger = logging.getLogger(__name__)

# Sentinel to signal "exit review, reject all remaining"
_EXIT = "exit"
_SKIP = "skip"
_SNOOZE = "snooze"


def format_verdict_for_review(verdict: Verdict, current: int = 0, total: int = 0) -> str:
    """Format a verdict for terminal display.

    Args:
        verdict: Verdict to format.
        current: 1-based index of current verdict in review.
        total: Total number of verdicts to review.

    Returns:
        Formatted string for review.
    """
    dead_link = verdict["dead_link"]
    candidate = verdict.get("candidate")
    confidence = verdict.get("confidence", 0)

    counter = f" [{current}/{total}]" if current and total else ""
    lines = [
        "",
        "-" * 50,
        f"  Review{counter}",
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


def format_review_summary(verdicts: list[Verdict], threshold: float) -> str:
    """Format a numbered summary of all verdicts before individual review.

    Args:
        verdicts: All verdicts to review.
        threshold: Confidence threshold for auto-approval.

    Returns:
        Formatted summary string.
    """
    if not verdicts:
        return ""

    lines = [
        "",
        "=" * 50,
        f"  Findings Summary ({len(verdicts)} total)",
        "=" * 50,
    ]
    for i, verdict in enumerate(verdicts, start=1):
        dl = verdict["dead_link"]
        confidence = verdict.get("confidence", 0)
        candidate = verdict.get("candidate")
        auto = " (auto)" if confidence >= threshold else ""
        replacement = candidate["url"] if candidate else "(no candidate)"
        lines.append(f"  {i}. {dl['url']}")
        lines.append(f"     {dl['source_file']}:{dl['line_number']}  {confidence:.0%}{auto}")
        lines.append(f"     -> {replacement}")
    lines.append("=" * 50)
    return "\n".join(lines)


def prompt_user_approval(verdict: Verdict) -> bool | str:
    """Interactive prompt for user to approve/reject/skip/snooze/exit.

    Args:
        verdict: Verdict to review.

    Returns:
        True if approved, False if rejected, "skip" to skip,
        "snooze" to snooze for recheck, "exit" to abort.

    Raises:
        KeyboardInterrupt: If user presses Ctrl+C (aborts pipeline).
    """
    response = input("[a]pprove / [r]eject / [s]kip / snoo[z]e / e[x]it: ").strip().lower()

    if response in ("a", "approve", "y", "yes"):
        return True
    if response in ("s", "skip"):
        return _SKIP
    if response in ("z", "snooze"):
        return _SNOOZE
    if response in ("x", "exit", "q", "quit"):
        return _EXIT

    # "r", "reject", "n", "no", or anything else -> reject
    return False


def _snooze_to_db(state: PipelineState, verdict: Verdict) -> None:
    """Write a snoozed finding to the recheck queue.

    Opens UnifiedDatabase using state["db_path"], writes the snooze entry,
    then closes the connection. Logs and continues on error.

    Args:
        state: Current pipeline state (needs db_path, repo_owner, repo_name_short).
        verdict: The verdict being snoozed.
    """
    try:
        from gh_link_auditor.unified_db import UnifiedDatabase

        db_path = state.get("db_path", "")
        if not db_path:
            logger.warning("No db_path in state; cannot snooze to recheck queue")
            return

        repo_owner = state.get("repo_owner", "")
        repo_name_short = state.get("repo_name_short", "")
        if repo_owner and repo_name_short:
            repo_full_name = f"{repo_owner}/{repo_name_short}"
        else:
            repo_full_name = state.get("target", "")

        dead_link = verdict["dead_link"]
        url = dead_link["url"]
        source_file = dead_link["source_file"]

        with UnifiedDatabase(db_path) as db:
            entry_id = db.snooze_finding(
                url=url,
                repo_full_name=repo_full_name,
                source_file=source_file,
                snooze_days=7,
                reason="Snoozed during HITL review",
            )
            logger.info("Snoozed %s to recheck queue (entry %d)", url, entry_id)
    except Exception:
        logger.exception("Failed to write snooze to recheck queue")


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
    total = len(verdicts)

    # Show numbered summary before individual review
    needs_review = not dry_run and any(v.get("confidence", 0) < threshold for v in verdicts)
    if needs_review and verdicts:
        print(format_review_summary(verdicts, threshold))

    for idx, verdict in enumerate(verdicts, start=1):
        confidence = verdict.get("confidence", 0)

        if dry_run or confidence >= threshold:
            # Auto-approve high confidence or skip review in dry run
            updated = dict(verdict)
            updated["approved"] = True
            reviewed.append(updated)  # type: ignore[arg-type]
        elif exit_review:
            # User chose exit -- reject all remaining
            updated = dict(verdict)
            updated["approved"] = False
            reviewed.append(updated)  # type: ignore[arg-type]
        else:
            # Present to user for review
            print(format_verdict_for_review(verdict, current=idx, total=total))
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
            elif result is _SNOOZE:
                # Snooze: mark as not-approved, write to recheck queue
                updated = dict(verdict)
                updated["approved"] = False
                reviewed.append(updated)  # type: ignore[arg-type]
                _snooze_to_db(state, verdict)
            else:
                updated = dict(verdict)
                updated["approved"] = bool(result)
                reviewed.append(updated)  # type: ignore[arg-type]

    state["reviewed_verdicts"] = reviewed
    state["review_aborted"] = exit_review
    return state
