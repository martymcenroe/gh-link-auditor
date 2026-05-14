"""Stage 4 — rank findings, pick top-3 per repo, render report (#218)."""

from __future__ import annotations

import logging
import statistics
from typing import Any

from gh_link_auditor.bulk_scan import storage
from gh_link_auditor.bulk_scan.config import (
    SURFACE_CONFIDENCE_THRESHOLD,
    TOP_N_PER_REPO,
)
from gh_link_auditor.unified_db import UnifiedDatabase

logger = logging.getLogger(__name__)


def select_top_n_per_repo(
    candidates: list[dict[str, Any]],
    top_n: int = TOP_N_PER_REPO,
    min_confidence: float = SURFACE_CONFIDENCE_THRESHOLD,
) -> list[dict[str, Any]]:
    """Pick best ``top_n`` candidates per repo, sorted by confidence desc.

    Filters to candidates with confidence >= ``min_confidence`` first.
    """
    eligible = [c for c in candidates if (c.get("confidence") or 0) >= min_confidence]
    eligible.sort(key=lambda c: (c["repo_full_name"], -(c.get("confidence") or 0)))
    surfaced: list[dict[str, Any]] = []
    last_repo: str | None = None
    repo_count = 0
    for c in eligible:
        if c["repo_full_name"] != last_repo:
            last_repo = c["repo_full_name"]
            repo_count = 0
        if repo_count < top_n:
            surfaced.append(c)
            repo_count += 1
    return surfaced


def mark_surfaced_for_run(db: UnifiedDatabase, run_id: str) -> int:
    """Score, filter, and persist surfaced flags for a run. Returns count surfaced."""
    rows = db._conn.execute(
        """SELECT id, run_id, repo_full_name, source_file, line_number,
                  dead_url, candidate_url, method, tier, similarity_score,
                  verified_live, confidence, surfaced
           FROM bulk_scan_findings WHERE run_id = ?""",
        (run_id,),
    ).fetchall()
    candidates = [dict(r) for r in rows]
    chosen = select_top_n_per_repo(candidates)
    chosen_ids = [c["id"] for c in chosen]
    storage.mark_findings_surfaced(db, chosen_ids)
    repo_counts: dict[str, int] = {}
    for c in chosen:
        repo_counts[c["repo_full_name"]] = repo_counts.get(c["repo_full_name"], 0) + 1
    for repo, cnt in repo_counts.items():
        storage.update_repo_status(db, run_id, repo, "done", surface_candidate_count=cnt)
    return len(chosen)


def quality_sample_median(db: UnifiedDatabase, run_id: str, sample_size: int = 100) -> float | None:
    """Median confidence over the most-recent ``sample_size`` candidates."""
    rows = db._conn.execute(
        """SELECT confidence FROM bulk_scan_findings
           WHERE run_id = ? ORDER BY created_at DESC LIMIT ?""",
        (run_id, sample_size),
    ).fetchall()
    vals = [r["confidence"] for r in rows if r["confidence"] is not None]
    if not vals:
        return None
    return statistics.median(vals)


def render_ranked_report(db: UnifiedDatabase, run_id: str) -> str:
    """Render the post-run markdown report. Casual register (#209 alignment)."""
    run = storage.get_run(db, run_id)
    counts = storage.get_repo_count_by_status(db, run_id)
    surfaced = storage.get_surfaced_findings_ranked(db, run_id)
    total_findings = storage.count_findings(db, run_id)

    lines = [
        f"# bulk scan — {run_id}",
        "",
        f"started: {run['started_at'] if run else '?'}",
        f"completed: {run['completed_at'] if run else '?'}",
        f"status: {run['status'] if run else '?'}",
        "",
        "## summary",
        "",
        f"- target repo count: {run['target_repo_count'] if run else '?'}",
        f"- repos by status: {counts}",
        f"- total findings (all tiers): {total_findings}",
        f"- surfaced (tier-1, >= {SURFACE_CONFIDENCE_THRESHOLD} conf): {len(surfaced)}",
        "",
        "## ranked surface (top per global confidence)",
        "",
    ]
    for i, f in enumerate(surfaced, start=1):
        loc = f["source_file"]
        if f["line_number"]:
            loc = f"{loc} line {f['line_number']}"
        lines.append(
            f"{i}. {f['repo_full_name']}  {loc}: "
            f"{f['dead_url']} -> {f['candidate_url']}  "
            f"({f['confidence']:.2f}, {f['method']})"
        )
    return "\n".join(lines)


def render_sample_report(db: UnifiedDatabase, run_id: str, sample_size: int = 100) -> str:
    """Render the mid-run quality-sample report (operator phone review)."""
    rows = db._conn.execute(
        """SELECT * FROM bulk_scan_findings
           WHERE run_id = ? ORDER BY created_at DESC LIMIT ?""",
        (run_id, sample_size),
    ).fetchall()
    samples = [dict(r) for r in rows]
    median = quality_sample_median(db, run_id, sample_size)
    lines = [
        f"# bulk scan sample — {run_id}",
        "",
        f"sample size: {len(samples)}",
        f"median confidence: {median:.2f}" if median is not None else "median confidence: n/a",
        "",
        "## sample (most recent first)",
        "",
    ]
    for s in samples:
        loc = s["source_file"]
        if s["line_number"]:
            loc = f"{loc} line {s['line_number']}"
        lines.append(
            f"- {s['repo_full_name']} {loc}: {s['dead_url']} -> {s['candidate_url']} "
            f"({s['confidence']:.2f}, {s['method']}, tier {s['tier']})"
        )
    return "\n".join(lines)
