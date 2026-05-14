"""Bulk-scan orchestrator: state machine, batching, checkpointing, signal handling (#218).

State transitions:
    selecting -> inventorying -> checking -> investigating -> scoring -> done

Failure-recoverable at every transition. Per-repo errors logged, scan continues.
``data/bulk-scan-abort`` file = clean stop request.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from gh_link_auditor.bulk_scan import (
    heartbeat,
    inventory,
    investigation,
    liveness,
    scoring,
    selection,
    storage,
)
from gh_link_auditor.bulk_scan.config import (
    ABORT_FILE,
    BATCH_SIZE,
    HEARTBEAT_FILE,
    HEARTBEAT_INTERVAL_S,
    QUALITY_MEDIAN_THRESHOLD,
    QUALITY_SAMPLE_AFTER_N_CANDIDATES,
    REPORT_FILE,
    SAMPLE_FILE,
)
from gh_link_auditor.unified_db import UnifiedDatabase

logger = logging.getLogger(__name__)


def _abort_requested() -> bool:
    return Path(ABORT_FILE).exists()


def _maybe_heartbeat(
    db: UnifiedDatabase,
    run_id: str,
    last_hb: float,
    *,
    sample_median: float | None = None,
) -> float:
    now = time.monotonic()
    if now - last_hb < HEARTBEAT_INTERVAL_S:
        return last_hb
    heartbeat.write_heartbeat(
        db,
        run_id,
        HEARTBEAT_FILE,
        sample_path=SAMPLE_FILE if Path(SAMPLE_FILE).exists() else None,
        sample_median=sample_median,
    )
    return now


def _maybe_write_sample(db: UnifiedDatabase, run_id: str) -> float | None:
    """If we've passed the sample-trigger threshold, write the sample file.
    Returns the median confidence if sample was (re)written, else None.
    """
    total = storage.count_findings(db, run_id)
    if total < QUALITY_SAMPLE_AFTER_N_CANDIDATES:
        return None
    median = scoring.quality_sample_median(db, run_id)
    body = scoring.render_sample_report(db, run_id, QUALITY_SAMPLE_AFTER_N_CANDIDATES)
    p = Path(SAMPLE_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return median


def _check_quality_stop_loss(db: UnifiedDatabase, run_id: str) -> bool:
    """If quality drops below floor after sample threshold, abort the run."""
    total = storage.count_findings(db, run_id)
    if total < QUALITY_SAMPLE_AFTER_N_CANDIDATES:
        return False
    median = scoring.quality_sample_median(db, run_id)
    if median is None:
        return False
    if median < QUALITY_MEDIAN_THRESHOLD:
        logger.warning(
            "quality stop-loss: median confidence %.2f < %.2f — aborting",
            median,
            QUALITY_MEDIAN_THRESHOLD,
        )
        storage.update_run_status(db, run_id, "quality_aborted", quality_aborted=True)
        return True
    return False


# -----------------------------------------------------------------------------
# Stage orchestrators
# -----------------------------------------------------------------------------


def run_selection(
    db: UnifiedDatabase,
    run_id: str,
    target_count: int,
    blacklisted_repos: set[str] | None = None,
) -> int:
    storage.update_run_status(db, run_id, "selecting")
    inserted = 0
    for repo in selection.select_python_repos(target_count, blacklisted_repos=blacklisted_repos):
        storage.upsert_repo(
            db,
            run_id,
            repo["full_name"],
            stars=repo.get("stars"),
            pushed_at=repo.get("pushed_at"),
            status="pending",
        )
        inserted += 1
    logger.info("selection: inserted %d repos for run %s", inserted, run_id)
    return inserted


def run_inventory(db: UnifiedDatabase, run_id: str, token: str | None = None) -> None:
    storage.update_run_status(db, run_id, "inventorying")
    api = inventory.build_api_client(token)
    raw = inventory.build_raw_client()
    last_hb = 0.0
    try:
        while True:
            if _abort_requested():
                storage.update_run_status(db, run_id, "aborted")
                return
            batch = storage.get_repos_by_status(db, run_id, "pending", limit=BATCH_SIZE)
            if not batch:
                break
            for repo in batch:
                full_name = repo["repo_full_name"]
                try:
                    result = inventory.inventory_repo(full_name, api, raw)
                    storage.update_repo_inventory(db, run_id, full_name, result["doc_files"], len(result["urls"]))
                    # Cache the (url, file, line) trios on the repo row via finding rows
                    # (lightweight: we just need to scan them in Stage 2/3; store them in findings
                    # with empty candidate fields, then update when investigated)
                    for url, src, ln in result["urls"]:
                        storage.add_finding(
                            db,
                            run_id,
                            full_name,
                            src,
                            ln,
                            url,
                            candidate_url="",  # placeholder; filled in Stage 3
                            method="pending",
                            tier=0,
                            similarity_score=None,
                            verified_live=False,
                            confidence=0.0,
                        )
                except Exception as e:
                    logger.warning("inventory failed: %s :: %s", full_name, e)
                    storage.update_repo_status(db, run_id, full_name, "error", error=str(e)[:500])
            last_hb = _maybe_heartbeat(db, run_id, last_hb)
    finally:
        api.close()
        raw.close()


def _get_pending_urls(db: UnifiedDatabase, run_id: str) -> list[str]:
    """Distinct dead_url values still showing method='pending' (= un-investigated)."""
    rows = db._conn.execute(
        "SELECT DISTINCT dead_url FROM bulk_scan_findings WHERE run_id = ? AND method = 'pending'",
        (run_id,),
    ).fetchall()
    return [r["dead_url"] for r in rows]


def run_liveness(db: UnifiedDatabase, run_id: str) -> dict[str, dict]:
    storage.update_run_status(db, run_id, "checking")
    urls = _get_pending_urls(db, run_id)
    if not urls:
        return {}
    logger.info("liveness: probing %d unique URLs", len(urls))
    return liveness.check_urls_bulk(urls)


def run_investigation(
    db: UnifiedDatabase,
    run_id: str,
    liveness_results: dict[str, dict],
) -> None:
    storage.update_run_status(db, run_id, "investigating")
    last_hb = 0.0
    sample_median: float | None = None
    repo_dead_counts: dict[str, int] = {}

    # Group pending findings by repo so we can update per-repo status after.
    rows = db._conn.execute(
        "SELECT id, repo_full_name, source_file, line_number, dead_url "
        "FROM bulk_scan_findings WHERE run_id = ? AND method = 'pending'",
        (run_id,),
    ).fetchall()
    pending = [dict(r) for r in rows]
    logger.info("investigation: %d pending findings to triage", len(pending))

    for i, finding in enumerate(pending, start=1):
        if _abort_requested():
            storage.update_run_status(db, run_id, "aborted")
            return
        url = finding["dead_url"]
        result = liveness_results.get(url, {})
        if not liveness.is_dead_result(result):
            # URL is alive — drop the placeholder finding row
            db._conn.execute("DELETE FROM bulk_scan_findings WHERE id = ?", (finding["id"],))
            db._conn.commit()
            continue

        repo_dead_counts[finding["repo_full_name"]] = repo_dead_counts.get(finding["repo_full_name"], 0) + 1

        candidates = investigation.investigate_one(url, result.get("status_code") or "error")
        tier1 = investigation.filter_tier1(candidates)
        # Replace the placeholder row with real candidates (delete + insert)
        db._conn.execute("DELETE FROM bulk_scan_findings WHERE id = ?", (finding["id"],))
        db._conn.commit()
        if not tier1:
            continue
        for c in tier1:
            confidence = investigation.compute_confidence(c)
            storage.add_finding(
                db,
                run_id,
                finding["repo_full_name"],
                finding["source_file"],
                finding["line_number"],
                url,
                c["candidate_url"],
                c["method"],
                c["tier"],
                c["similarity_score"],
                c["verified_live"],
                confidence,
            )

        # Mid-run sample + stop-loss check
        if i % BATCH_SIZE == 0:
            sample_median = _maybe_write_sample(db, run_id) or sample_median
            if _check_quality_stop_loss(db, run_id):
                return
            last_hb = _maybe_heartbeat(db, run_id, last_hb, sample_median=sample_median)

    for repo, cnt in repo_dead_counts.items():
        storage.update_repo_status(db, run_id, repo, "investigated", dead_url_count=cnt)


def run_scoring(db: UnifiedDatabase, run_id: str) -> None:
    storage.update_run_status(db, run_id, "scoring")
    surfaced = scoring.mark_surfaced_for_run(db, run_id)
    logger.info("scoring: %d candidates surfaced", surfaced)
    report = scoring.render_ranked_report(db, run_id)
    p = Path(REPORT_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(report, encoding="utf-8")
    storage.update_run_status(db, run_id, "done")


# -----------------------------------------------------------------------------
# Top-level orchestrator
# -----------------------------------------------------------------------------


def get_blacklisted_repos(db: UnifiedDatabase) -> set[str]:
    """Pull all repo_url blacklist entries and reduce to owner/name."""
    rows = db._conn.execute("SELECT repo_url FROM blacklist WHERE repo_url IS NOT NULL").fetchall()
    out: set[str] = set()
    for r in rows:
        url = r["repo_url"] or ""
        # https://github.com/owner/name -> owner/name
        if "github.com/" in url:
            out.add(url.split("github.com/", 1)[1].rstrip("/"))
    return out


def run_full(
    db: UnifiedDatabase,
    run_id: str,
    target_count: int,
    token: str | None = None,
    skip_selection: bool = False,
) -> dict[str, Any]:
    """End-to-end orchestration. Resumable: existing state respected."""
    run = storage.get_run(db, run_id)
    if run is None:
        storage.create_run(db, run_id, target_count, {"target_count": target_count})
        run = storage.get_run(db, run_id)

    if not skip_selection and run["status"] in ("selecting", None):
        run_selection(db, run_id, target_count, get_blacklisted_repos(db))

    if run["status"] in ("selecting", "inventorying"):
        run_inventory(db, run_id, token=token or os.environ.get("GITHUB_TOKEN"))

    run = storage.get_run(db, run_id)
    if run["status"] in ("inventorying", "checking"):
        liveness_results = run_liveness(db, run_id)
    else:
        liveness_results = {}

    run = storage.get_run(db, run_id)
    if run["status"] in ("checking", "investigating"):
        run_investigation(db, run_id, liveness_results)

    run = storage.get_run(db, run_id)
    if run["status"] not in ("aborted", "quality_aborted", "done"):
        run_scoring(db, run_id)

    heartbeat.write_heartbeat(db, run_id, HEARTBEAT_FILE)
    return storage.get_run(db, run_id) or {}
