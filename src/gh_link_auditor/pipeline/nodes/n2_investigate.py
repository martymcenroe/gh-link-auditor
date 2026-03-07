"""N2 Investigate node (Cheery).

Wraps LinkDetective to investigate dead links and find replacement candidates.

See LLD #22 §2.4 for n2_investigate specification.
"""

from __future__ import annotations

import logging

from gh_link_auditor.pipeline.state import (
    DeadLink,
    PipelineState,
    ReplacementCandidate,
)

logger = logging.getLogger(__name__)


def _run_investigation(dead_url: str, http_status: int | str):
    """Run LinkDetective investigation on a dead URL.

    Args:
        dead_url: The broken URL.
        http_status: HTTP status code or error string.

    Returns:
        ForensicReport from LinkDetective.
    """
    from gh_link_auditor.link_detective import LinkDetective

    detective = LinkDetective()
    return detective.investigate(dead_url, http_status)


def investigate_dead_link(dead_link: DeadLink) -> list[ReplacementCandidate]:
    """Investigate a single dead link for replacement candidates.

    Delegates to LinkDetective and converts results to ReplacementCandidate format.

    Args:
        dead_link: The dead link to investigate.

    Returns:
        List of ReplacementCandidate dicts.
    """
    try:
        report = _run_investigation(
            dead_link["url"],
            dead_link.get("http_status") or dead_link.get("error_type", "unknown"),
        )
    except Exception:
        logger.exception("Investigation failed for %s", dead_link["url"])
        return []

    candidates: list[ReplacementCandidate] = []
    for cr in report.investigation.candidate_replacements:
        candidates.append(
            ReplacementCandidate(
                url=cr.url,
                source=cr.method.value if hasattr(cr.method, "value") else str(cr.method),
                title=report.investigation.archive_title,
                snippet=report.investigation.archive_content_summary,
            )
        )

    return candidates


def n2_investigate(state: PipelineState) -> PipelineState:
    """N2 node: Investigate dead links for replacements (Cheery).

    For each dead link, runs investigation and collects candidates.

    Args:
        state: Current pipeline state.

    Returns:
        Updated PipelineState with candidates populated.
    """
    dead_links = state.get("dead_links", [])
    candidates: dict[str, list[ReplacementCandidate]] = {}

    if state.get("cost_limit_reached", False):
        state["candidates"] = candidates
        return state

    for dead_link in dead_links:
        url = dead_link["url"]
        try:
            found = investigate_dead_link(dead_link)
            candidates[url] = found
        except Exception:
            logger.exception("Error investigating %s", url)
            state["errors"] = state.get("errors", []) + [f"Investigation error for {url}"]
            candidates[url] = []

    state["candidates"] = candidates
    return state
