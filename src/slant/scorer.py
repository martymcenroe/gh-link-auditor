"""Main scoring engine for Slant.

Loads forensic reports, computes weighted signal scores for each
candidate replacement URL, and produces confidence-tiered verdicts.

See LLD #21 §2.5 "Scoring Engine Flow" for specification.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from slant.config import get_default_weights
from slant.models import (
    CandidateEntry,
    ForensicReportEntry,
    ScoringBreakdown,
    SignalWeights,
    Verdict,
    VerdictsFile,
)
from slant.signals.content import compare_content
from slant.signals.domain import match_domain
from slant.signals.redirect import check_redirect
from slant.signals.title import match_title
from slant.signals.url_path import compare_url_paths


def map_confidence_to_tier(confidence: int) -> str:
    """Map 0–100 composite score to verdict tier.

    Tiers (LLD #21 §2.5):
        - AUTO-APPROVE: >= 95
        - HUMAN-REVIEW: 75–94
        - LOW-CONFIDENCE: 50–74
        - INSUFFICIENT: < 50

    Args:
        confidence: Composite score 0–100.

    Returns:
        Tier string.
    """
    if confidence >= 95:
        return "AUTO-APPROVE"
    if confidence >= 75:
        return "HUMAN-REVIEW"
    if confidence >= 50:
        return "LOW-CONFIDENCE"
    return "INSUFFICIENT"


def score_candidate(
    dead_url: str,
    candidate: CandidateEntry,
    archived_title: str,
    archived_content: str,
    weights: SignalWeights,
) -> tuple[float, ScoringBreakdown]:
    """Compute composite score and breakdown for a single candidate.

    Each signal returns 0.0–1.0, multiplied by its weight to produce
    a weighted score. The composite is the sum of all weighted scores.

    Args:
        dead_url: The original dead URL.
        candidate: Candidate entry with url and source.
        archived_title: Title from archived version.
        archived_content: Plain text from archived version.
        weights: Signal weight configuration.

    Returns:
        Tuple of (composite_score, ScoringBreakdown).
    """
    candidate_url = candidate["url"]

    redirect_raw = check_redirect(dead_url, candidate_url)
    title_raw = match_title(candidate_url, archived_title)
    content_raw = compare_content(candidate_url, archived_content)
    url_path_raw = compare_url_paths(dead_url, candidate_url)
    domain_raw = match_domain(dead_url, candidate_url)

    breakdown = ScoringBreakdown(
        redirect=redirect_raw * weights["redirect"],
        title_match=title_raw * weights["title"],
        content_similarity=content_raw * weights["content"],
        url_similarity=url_path_raw * weights["url_path"],
        domain_match=domain_raw * weights["domain"],
    )

    composite = (
        breakdown["redirect"]
        + breakdown["title_match"]
        + breakdown["content_similarity"]
        + breakdown["url_similarity"]
        + breakdown["domain_match"]
    )

    return composite, breakdown


def score_dead_link(entry: ForensicReportEntry, weights: SignalWeights) -> Verdict:
    """Score all candidates for a single dead link and return best verdict.

    If no candidates, returns INSUFFICIENT with confidence=0.

    Args:
        entry: Forensic report entry with dead URL and candidates.
        weights: Signal weight configuration.

    Returns:
        Verdict for this dead link.
    """
    if not entry["candidates"]:
        return Verdict(
            dead_url=entry["dead_url"],
            verdict="INSUFFICIENT",
            confidence=0,
            replacement_url=None,
            scoring_breakdown=ScoringBreakdown(
                redirect=0,
                title_match=0,
                content_similarity=0,
                url_similarity=0,
                domain_match=0,
            ),
            human_decision=None,
            decided_at=None,
        )

    best_score = -1.0
    best_breakdown = None
    best_url = None

    for candidate in entry["candidates"]:
        composite, breakdown = score_candidate(
            entry["dead_url"],
            candidate,
            entry["archived_title"],
            entry["archived_content"],
            weights,
        )
        if composite > best_score:
            best_score = composite
            best_breakdown = breakdown
            best_url = candidate["url"]

    confidence = int(round(best_score))
    tier = map_confidence_to_tier(confidence)

    human_decision = None
    decided_at = None
    if tier == "AUTO-APPROVE":
        human_decision = "auto"
        decided_at = datetime.now(timezone.utc).isoformat()

    return Verdict(
        dead_url=entry["dead_url"],
        verdict=tier,
        confidence=confidence,
        replacement_url=best_url,
        scoring_breakdown=best_breakdown,
        human_decision=human_decision,
        decided_at=decided_at,
    )


def score_report(report_path: Path, weights: SignalWeights | None = None) -> VerdictsFile:
    """Load forensic report and produce verdicts for all dead links.

    Args:
        report_path: Path to forensic report JSON.
        weights: Signal weights, or None for defaults.

    Returns:
        VerdictsFile with verdicts for each dead link.
    """
    if weights is None:
        weights = get_default_weights()

    data = json.loads(report_path.read_text())
    entries = data["dead_links"]

    verdicts = []
    for entry_data in entries:
        entry = ForensicReportEntry(
            dead_url=entry_data["dead_url"],
            archived_url=entry_data.get("archived_url", ""),
            archived_title=entry_data.get("archived_title", ""),
            archived_content=entry_data.get("archived_content", ""),
            investigation_method=entry_data.get("investigation_method", ""),
            candidates=[CandidateEntry(url=c["url"], source=c["source"]) for c in entry_data.get("candidates", [])],
        )
        verdict = score_dead_link(entry, weights)
        verdicts.append(verdict)

    return VerdictsFile(
        generated_at=datetime.now(timezone.utc).isoformat(),
        source_report=str(report_path),
        verdicts=verdicts,
    )


def write_verdicts(verdicts: VerdictsFile, output_path: Path) -> None:
    """Write verdicts to JSON file with atomic write via temp file + rename.

    Args:
        verdicts: VerdictsFile to write.
        output_path: Destination path.
    """
    import os

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: write to temp file in same directory, then rename
    fd, tmp_path_str = tempfile.mkstemp(
        dir=str(output_path.parent),
        suffix=".tmp",
    )
    tmp_path = Path(tmp_path_str)
    try:
        # Close the fd first — Windows locks files with open handles
        os.close(fd)
        tmp_path.write_text(json.dumps(verdicts, indent=2))
        tmp_path.replace(output_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
