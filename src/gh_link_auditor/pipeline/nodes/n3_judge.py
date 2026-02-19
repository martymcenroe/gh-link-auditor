"""N3 Judge node (Mr. Slant).

Scores replacement candidates using Slant's algorithmic scoring engine.
No LLM calls by default — pure signal-based scoring.

See LLD #22 §2.4 for n3_judge specification.
"""

from __future__ import annotations

import logging

from gh_link_auditor.pipeline.state import (
    DeadLink,
    PipelineState,
    ReplacementCandidate,
    Verdict,
)

logger = logging.getLogger(__name__)


def _score_candidates(
    dead_link: DeadLink,
    candidates: list[ReplacementCandidate],
) -> Verdict:
    """Score candidates using Slant scoring engine.

    Args:
        dead_link: The dead link being judged.
        candidates: List of replacement candidates.

    Returns:
        Verdict dict with best candidate and confidence.
    """
    from slant.config import get_default_weights
    from slant.models import CandidateEntry, ForensicReportEntry
    from slant.scorer import score_dead_link

    weights = get_default_weights()

    # Convert pipeline types to Slant types
    slant_candidates = [
        CandidateEntry(url=c["url"], source=c["source"]) for c in candidates
    ]
    entry = ForensicReportEntry(
        dead_url=dead_link["url"],
        archived_url="",
        archived_title="",
        archived_content="",
        investigation_method=candidates[0]["source"] if candidates else "",
        candidates=slant_candidates,
    )

    slant_verdict = score_dead_link(entry, weights)

    # Convert Slant Verdict to pipeline Verdict
    best_candidate = None
    if slant_verdict.get("replacement_url"):
        # Find matching candidate
        for c in candidates:
            if c["url"] == slant_verdict["replacement_url"]:
                best_candidate = c
                break

    confidence = slant_verdict.get("confidence", 0) / 100.0

    return Verdict(
        dead_link=dead_link,
        candidate=best_candidate,
        confidence=confidence,
        reasoning=f"Slant score: {slant_verdict.get('confidence', 0)}/100 ({slant_verdict.get('verdict', 'UNKNOWN')})",
        approved=None,
    )


def judge_candidates(
    dead_link: DeadLink,
    candidates: list[ReplacementCandidate],
) -> Verdict:
    """Judge replacement candidates for a dead link.

    Args:
        dead_link: The dead link being judged.
        candidates: Replacement candidates to evaluate.

    Returns:
        Verdict dict.
    """
    if not candidates:
        return Verdict(
            dead_link=dead_link,
            candidate=None,
            confidence=0,
            reasoning="No candidates available",
            approved=None,
        )

    try:
        return _score_candidates(dead_link, candidates)
    except Exception:
        logger.exception("Scoring failed for %s", dead_link["url"])
        return Verdict(
            dead_link=dead_link,
            candidate=None,
            confidence=0,
            reasoning="Scoring error",
            approved=None,
        )


def n3_judge(state: PipelineState) -> PipelineState:
    """N3 node: Judge replacement candidates (Mr. Slant).

    Scores all dead links' candidates and produces verdicts.

    Args:
        state: Current pipeline state.

    Returns:
        Updated PipelineState with verdicts populated.
    """
    dead_links = state.get("dead_links", [])
    candidates = state.get("candidates", {})
    verdicts: list[Verdict] = []

    for dead_link in dead_links:
        url = dead_link["url"]
        link_candidates = candidates.get(url, [])
        try:
            verdict = judge_candidates(dead_link, link_candidates)
            verdicts.append(verdict)
        except Exception:
            logger.exception("Judge error for %s", url)
            state["errors"] = state.get("errors", []) + [f"Judge error for {url}"]
            verdicts.append(
                Verdict(
                    dead_link=dead_link,
                    candidate=None,
                    confidence=0,
                    reasoning="Judge error",
                    approved=None,
                )
            )

    state["verdicts"] = verdicts
    return state
