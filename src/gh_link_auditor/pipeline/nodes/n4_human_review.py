"""N4 Human Review node.

Terminal-based human-in-the-loop review for low-confidence verdicts.

See LLD #22 section 2.4 for n4_human_review specification.
Updated in #148 with snooze key binding.
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus, urlparse

from gh_link_auditor.pipeline.state import PipelineState, ReplacementCandidate, Verdict

logger = logging.getLogger(__name__)

# Sentinels for prompt_user_approval. Compared with `is`, hence string singletons.
_EXIT = "exit"
_SKIP = "skip"
_SNOOZE = "snooze"
_LIVE = "live"
_DEAD = "dead"


def _prompt_replacement_url() -> str | None:
    """Prompt operator for a manually-typed replacement URL (#214).

    Returns the URL if valid (http/https), or None if cancelled (empty input).
    Re-prompts on invalid input.
    """
    while True:
        url = input("  Replacement URL (or Enter to cancel): ").strip()
        if not url:
            return None
        if url.startswith(("http://", "https://")):
            return url
        print("  Invalid — must start with http:// or https://")


def generate_google_searches(dead_url: str) -> list[str]:
    """Construct 3-5 diagnostic Google search URLs for a dead URL (#196).

    Pure function; no network. Returned URLs are clickable in standard terminals.

    Strategy templates:
        - ``site:{domain} {humanized_last_path_segment}`` — what's on the site today?
        - ``"{humanized_name}" replacement`` — did it get renamed?
        - ``"{humanized_name}" successor OR deprecated`` — is it dead?
        - ``"{full_dead_url}"`` — triangulation: who else links to this?
    """
    parsed = urlparse(dead_url)
    domain = (parsed.hostname or "").strip()
    last_segment = ""
    if parsed.path:
        parts = [p for p in parsed.path.rstrip("/").split("/") if p]
        if parts:
            last_segment = parts[-1].replace("-", " ").replace("_", " ").strip()
    name = last_segment

    base = "https://www.google.com/search?q="
    searches: list[str] = []
    if domain and name:
        searches.append(base + quote_plus(f"site:{domain} {name}"))
    elif domain:
        searches.append(base + quote_plus(f"site:{domain}"))
    if name:
        searches.append(base + quote_plus(f'"{name}" replacement'))
        searches.append(base + quote_plus(f'"{name}" successor OR deprecated OR shutdown'))
    # Triangulation: search for the literal URL.
    searches.append(base + quote_plus(f'"{dead_url}"'))
    return searches


def build_github_source_url(
    repo_owner: str | None,
    repo_name_short: str | None,
    source_file: str,
    line_number: int,
) -> str | None:
    """Construct a GitHub blob URL with a line anchor (#194).

    Uses the ``HEAD`` ref so the URL resolves to the repo's default branch
    automatically — no need to fetch the branch name ahead of time.

    Returns ``None`` when owner or repo is missing (e.g., local-path target).
    """
    if not repo_owner or not repo_name_short:
        return None
    return f"https://github.com/{repo_owner}/{repo_name_short}/blob/HEAD/{source_file}#L{line_number}"


def format_verdict_for_review(
    verdict: Verdict,
    current: int = 0,
    total: int = 0,
    github_source_url: str | None = None,
) -> str:
    """Format a verdict for terminal display.

    Args:
        verdict: Verdict to format.
        current: 1-based index of current verdict in review.
        total: Total number of verdicts to review.
        github_source_url: Optional clickable GitHub blob URL with line anchor
            (#194). Caller constructs via :func:`build_github_source_url`.

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
    ]
    if github_source_url:
        lines.append(f"  Source:    {github_source_url}")
    lines.append(f"  Confidence: {confidence:.0%}")

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
    """Interactive prompt for the operator to act on a verdict.

    Returns one of:
        - ``True`` — approve (the fix lands in the PR)
        - ``False`` — reject (the dead link stays, no fix)
        - ``_SKIP`` — defer; pipeline continues to next verdict
        - ``_SNOOZE`` — push to recheck queue (#148)
        - ``_LIVE`` — operator confirms the URL is actually live, log as false
          positive (#195). Treated like reject for pipeline flow.
        - ``_EXIT`` — abort review, reject everything remaining

    The ``[g]oogle`` option (#196) prints diagnostic search URLs and
    re-prompts without advancing.

    Raises:
        KeyboardInterrupt: If the operator presses Ctrl+C (aborts pipeline).
    """
    dead_url = verdict["dead_link"]["url"]
    prompt = "[a]pprove / [r]eject / [m]anual / [s]kip / snoo[z]e / [l]ive / [d]ead-product / [g]oogle / e[x]it: "
    while True:
        response = input(prompt).strip().lower()

        if response in ("g", "google"):
            print("\n  Google searches (click to open in your browser):")
            for url in generate_google_searches(dead_url):
                print(f"    {url}")
            print()
            continue  # re-prompt; doesn't advance the verdict

        if response in ("m", "manual"):
            new_url = _prompt_replacement_url()
            if new_url is None:
                continue  # cancelled — back to main prompt
            verdict["candidate"] = ReplacementCandidate(
                url=new_url,
                source="manual",
                title=None,
                snippet=None,
            )
            return True

        if response in ("a", "approve", "y", "yes"):
            return True
        if response in ("s", "skip"):
            return _SKIP
        if response in ("z", "snooze"):
            return _SNOOZE
        if response in ("l", "live"):
            return _LIVE
        if response in ("d", "dead", "dead-product"):
            return _DEAD
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


def _rewrite_queue_to_db(state: PipelineState, verdict: Verdict) -> None:
    """Persist a [d]ead-product flag to the rewrite queue (#212).

    Operator-confirmed dead URL whose section needs structural rewrite, not URL
    swap. Excluded from this PR's fixes; surfaces in ``ghla rewrite-queue`` for
    later batching into an upstream content-rewrite issue.
    """
    try:
        from gh_link_auditor.unified_db import UnifiedDatabase

        db_path = state.get("db_path", "")
        if not db_path:
            logger.warning("No db_path in state; cannot write to rewrite queue")
            return

        repo_owner = state.get("repo_owner", "")
        repo_name_short = state.get("repo_name_short", "")
        if repo_owner and repo_name_short:
            repo_full_name = f"{repo_owner}/{repo_name_short}"
        else:
            repo_full_name = state.get("target", "")

        dead_link = verdict["dead_link"]
        with UnifiedDatabase(db_path) as db:
            entry_id = db.add_to_rewrite_queue(
                dead_url=dead_link["url"],
                source_file=dead_link["source_file"],
                line_number=dead_link.get("line_number"),
                repo_full_name=repo_full_name,
                reason="dead product / section needs rewrite",
            )
            logger.info("Queued %s for deeper rewrite (entry %d)", dead_link["url"], entry_id)
    except Exception:
        logger.exception("Failed to write to rewrite queue")


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
    false_positives: list[dict] = []
    rewrite_queued: list[dict] = []
    exit_review = False
    total = len(verdicts)
    repo_owner = state.get("repo_owner", "")
    repo_name_short = state.get("repo_name_short", "")

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
            dl = verdict["dead_link"]
            github_url = build_github_source_url(
                repo_owner,
                repo_name_short,
                dl["source_file"],
                dl["line_number"],
            )
            print(format_verdict_for_review(verdict, current=idx, total=total, github_source_url=github_url))
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
            elif result is _LIVE:
                # Operator confirmed actually-live: log as false positive,
                # treat as reject for pipeline flow (#195).
                updated = dict(verdict)
                updated["approved"] = False
                reviewed.append(updated)  # type: ignore[arg-type]
                false_positives.append(
                    {
                        "url": dl["url"],
                        "source_file": dl["source_file"],
                        "line_number": dl["line_number"],
                        "http_status": dl.get("http_status"),
                    }
                )
                print(f"  → logged as false positive: {dl['url']}")
            elif result is _DEAD:
                # Operator confirmed dead-product / deferred-rewrite candidate (#212).
                # Excluded from this PR's fixes; queued for upstream rewrite issue.
                updated = dict(verdict)
                updated["approved"] = False
                reviewed.append(updated)  # type: ignore[arg-type]
                rewrite_queued.append(
                    {
                        "url": dl["url"],
                        "source_file": dl["source_file"],
                        "line_number": dl["line_number"],
                    }
                )
                _rewrite_queue_to_db(state, verdict)
                print(f"  → queued for deeper rewrite: {dl['url']}")
            else:
                updated = dict(verdict)
                updated["approved"] = bool(result)
                reviewed.append(updated)  # type: ignore[arg-type]

    if false_positives:
        print(f"\n  {len(false_positives)} URL(s) flagged as actually-live (false positives):")
        for fp in false_positives:
            print(f"    - {fp['url']} ({fp['source_file']}:{fp['line_number']})")

    if rewrite_queued:
        print(f"\n  {len(rewrite_queued)} URL(s) queued for deeper rewrite:")
        for rq in rewrite_queued:
            print(f"    - {rq['url']} ({rq['source_file']}:{rq['line_number']})")
        print("  Run `ghla rewrite-queue export --repo <owner/name>` to draft the upstream issue.")

    state["reviewed_verdicts"] = reviewed
    state["review_aborted"] = exit_review
    state["false_positives"] = false_positives  # type: ignore[typeddict-unknown-key]
    state["rewrite_queued"] = rewrite_queued  # type: ignore[typeddict-unknown-key]
    return state
