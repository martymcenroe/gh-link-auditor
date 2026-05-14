"""Heartbeat file writer for the bulk scan (#218).

Operator-visible status the operator can ``cat`` from their phone over SSH or
shared filesystem. Updated on a timer from a worker thread.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from gh_link_auditor.bulk_scan import storage
from gh_link_auditor.unified_db import UnifiedDatabase

logger = logging.getLogger(__name__)


def write_heartbeat(
    db: UnifiedDatabase,
    run_id: str,
    out_path: str | Path,
    *,
    sample_path: str | Path | None = None,
    sample_median: float | None = None,
) -> None:
    """Snapshot DB state into a small text file."""
    run = storage.get_run(db, run_id)
    if run is None:
        return
    counts = storage.get_repo_count_by_status(db, run_id)
    total_findings = storage.count_findings(db, run_id)
    surfaced = storage.count_findings(db, run_id, surfaced=True)
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        f"run_id: {run_id}",
        f"status: {run['status']}",
        f"started_at: {run['started_at']}",
        f"target_repo_count: {run.get('target_repo_count')}",
        f"repos_by_status: {counts}",
        f"total_findings: {total_findings}",
        f"surfaced_findings: {surfaced}",
        f"last_update: {now}",
    ]
    if sample_path is not None:
        lines.append(f"quality_sample: {sample_path}")
    if sample_median is not None:
        lines.append(f"sample_median_confidence: {sample_median:.2f}")
    if run.get("quality_aborted"):
        lines.append("QUALITY_ABORTED: median confidence dropped below threshold")
    if run.get("error"):
        lines.append(f"error: {run['error']}")
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
