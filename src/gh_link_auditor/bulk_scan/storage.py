"""DB helpers for the bulk scan tables (#218)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from gh_link_auditor.unified_db import UnifiedDatabase

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Run lifecycle ---


def create_run(
    db: UnifiedDatabase,
    run_id: str,
    target_repo_count: int,
    config: dict[str, Any],
) -> None:
    """Insert a new run row in status='selecting'."""
    with db._conn:
        db._conn.execute(
            """INSERT INTO bulk_scan_runs
               (run_id, started_at, status, target_repo_count, config_json)
               VALUES (?, ?, 'selecting', ?, ?)""",
            (run_id, _now_iso(), target_repo_count, json.dumps(config)),
        )


def update_run_status(
    db: UnifiedDatabase,
    run_id: str,
    status: str,
    error: str | None = None,
    quality_aborted: bool = False,
) -> None:
    completed_at = _now_iso() if status in ("done", "aborted", "quality_aborted") else None
    with db._conn:
        db._conn.execute(
            """UPDATE bulk_scan_runs
               SET status = ?, error = ?, quality_aborted = ?, completed_at = COALESCE(?, completed_at)
               WHERE run_id = ?""",
            (status, error, 1 if quality_aborted else 0, completed_at, run_id),
        )


def get_run(db: UnifiedDatabase, run_id: str) -> dict[str, Any] | None:
    row = db._conn.execute("SELECT * FROM bulk_scan_runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_runs(db: UnifiedDatabase, limit: int = 20) -> list[dict[str, Any]]:
    rows = db._conn.execute("SELECT * FROM bulk_scan_runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# --- Reconcile abandoned runs (#426) ---

# The exact set update_run_status stamps completed_at for — keep in sync there.
TERMINAL_RUN_STATUSES = ("done", "aborted", "quality_aborted")


def find_abandoned_runs(
    db: UnifiedDatabase,
    older_than_hours: float = 24.0,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Non-terminal runs older than the threshold with no live process lock.

    Conservative by construction: a run with ANY row in ``bulk_scan_locks``
    is treated as live and never returned — the lock is the liveness signal
    (#244); stale-lock cleanup is the lock owner's job. ``now`` is injectable
    so tests never assert against wall-clock.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=older_than_hours)).isoformat()
    placeholders = ",".join("?" for _ in TERMINAL_RUN_STATUSES)
    rows = db._conn.execute(
        f"""SELECT * FROM bulk_scan_runs
            WHERE status NOT IN ({placeholders})
              AND started_at < ?
              AND run_id NOT IN (SELECT run_id FROM bulk_scan_locks)
            ORDER BY started_at""",  # noqa: S608
        (*TERMINAL_RUN_STATUSES, cutoff),
    ).fetchall()
    return [dict(r) for r in rows]


def reconcile_abandoned_runs(
    db: UnifiedDatabase,
    older_than_hours: float = 24.0,
    now: datetime | None = None,
) -> list[str]:
    """Flip abandoned runs to ``aborted`` with an explanatory error (#426)."""
    abandoned = find_abandoned_runs(db, older_than_hours=older_than_hours, now=now)
    for run in abandoned:
        update_run_status(
            db,
            run["run_id"],
            "aborted",
            error=(f"reconciled: abandoned in status={run['status']!r} with no activity since {run['started_at']}"),
        )
        logger.info("reconciled abandoned run %s (was %s)", run["run_id"], run["status"])
    return [run["run_id"] for run in abandoned]


# --- Repos ---


def upsert_repo(
    db: UnifiedDatabase,
    run_id: str,
    repo_full_name: str,
    stars: int | None = None,
    pushed_at: str | None = None,
    status: str = "pending",
) -> None:
    """Insert or update a per-repo row."""
    with db._conn:
        db._conn.execute(
            """INSERT INTO bulk_scan_repos
               (run_id, repo_full_name, stars, pushed_at, status, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(run_id, repo_full_name) DO UPDATE SET
                 stars = excluded.stars,
                 pushed_at = excluded.pushed_at,
                 status = excluded.status,
                 updated_at = excluded.updated_at""",
            (run_id, repo_full_name, stars, pushed_at, status, _now_iso()),
        )


def update_repo_inventory(
    db: UnifiedDatabase,
    run_id: str,
    repo_full_name: str,
    doc_files: list[str],
    url_count: int,
) -> None:
    with db._conn:
        db._conn.execute(
            """UPDATE bulk_scan_repos
               SET doc_files_json = ?, url_count = ?, status = 'inventoried', updated_at = ?
               WHERE run_id = ? AND repo_full_name = ?""",
            (json.dumps(doc_files), url_count, _now_iso(), run_id, repo_full_name),
        )


def update_repo_status(
    db: UnifiedDatabase,
    run_id: str,
    repo_full_name: str,
    status: str,
    error: str | None = None,
    dead_url_count: int | None = None,
    surface_candidate_count: int | None = None,
) -> None:
    fields = ["status = ?", "updated_at = ?"]
    values: list[Any] = [status, _now_iso()]
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    if dead_url_count is not None:
        fields.append("dead_url_count = ?")
        values.append(dead_url_count)
    if surface_candidate_count is not None:
        fields.append("surface_candidate_count = ?")
        values.append(surface_candidate_count)
    values.extend([run_id, repo_full_name])
    with db._conn:
        db._conn.execute(
            f"UPDATE bulk_scan_repos SET {', '.join(fields)} "  # noqa: S608
            f"WHERE run_id = ? AND repo_full_name = ?",
            tuple(values),
        )


def apply_repo_rename(
    db: UnifiedDatabase,
    run_id: str,
    old_full_name: str,
    new_full_name: str,
) -> bool:
    """Move a repo row from ``old_full_name`` to ``new_full_name`` (#250).

    Updates ``bulk_scan_repos`` primary key in place and records the old name
    in ``previous_full_name``. Also propagates the rename to any existing
    ``bulk_scan_findings`` rows so they stay linked to the repo row.

    Returns ``True`` when the rename was applied. Returns ``False`` if a row
    already exists for ``(run_id, new_full_name)`` — a rare PK-collision case
    that we don't try to merge automatically; the caller should continue
    operating under ``old_full_name`` rather than corrupt either row.
    """
    if old_full_name == new_full_name:
        return False
    with db._conn:
        existing = db._conn.execute(
            "SELECT 1 FROM bulk_scan_repos WHERE run_id = ? AND repo_full_name = ?",
            (run_id, new_full_name),
        ).fetchone()
        if existing is not None:
            logger.warning(
                "apply_repo_rename: PK collision; both %r and %r exist in run %s — not renaming",
                old_full_name,
                new_full_name,
                run_id,
            )
            return False
        db._conn.execute(
            "UPDATE bulk_scan_repos SET repo_full_name = ?, previous_full_name = ?, updated_at = ? "
            "WHERE run_id = ? AND repo_full_name = ?",
            (new_full_name, old_full_name, _now_iso(), run_id, old_full_name),
        )
        db._conn.execute(
            "UPDATE bulk_scan_findings SET repo_full_name = ? WHERE run_id = ? AND repo_full_name = ?",
            (new_full_name, run_id, old_full_name),
        )
    return True


def get_repos_by_status(
    db: UnifiedDatabase,
    run_id: str,
    status: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM bulk_scan_repos WHERE run_id = ? AND status = ?"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    rows = db._conn.execute(sql, (run_id, status)).fetchall()
    return [dict(r) for r in rows]


def get_repo_count_by_status(db: UnifiedDatabase, run_id: str) -> dict[str, int]:
    rows = db._conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM bulk_scan_repos WHERE run_id = ? GROUP BY status",
        (run_id,),
    ).fetchall()
    return {r["status"]: r["cnt"] for r in rows}


# --- Findings ---


def add_finding(
    db: UnifiedDatabase,
    run_id: str,
    repo_full_name: str,
    source_file: str,
    line_number: int | None,
    dead_url: str,
    candidate_url: str,
    method: str,
    tier: int,
    similarity_score: float | None,
    verified_live: bool,
    confidence: float,
    surfaced: bool = False,
) -> int:
    with db._conn:
        cursor = db._conn.execute(
            """INSERT INTO bulk_scan_findings
               (run_id, repo_full_name, source_file, line_number, dead_url,
                candidate_url, method, tier, similarity_score, verified_live,
                confidence, surfaced, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                repo_full_name,
                source_file,
                line_number,
                dead_url,
                candidate_url,
                method,
                tier,
                similarity_score,
                1 if verified_live else 0,
                confidence,
                1 if surfaced else 0,
                _now_iso(),
            ),
        )
        return cursor.lastrowid  # type: ignore[return-value]


def mark_findings_surfaced(db: UnifiedDatabase, finding_ids: list[int]) -> None:
    if not finding_ids:
        return
    placeholders = ",".join("?" for _ in finding_ids)
    with db._conn:
        db._conn.execute(
            f"UPDATE bulk_scan_findings SET surfaced = 1 WHERE id IN ({placeholders})",  # noqa: S608
            tuple(finding_ids),
        )


def get_findings_for_repo(
    db: UnifiedDatabase,
    run_id: str,
    repo_full_name: str,
    tier: int | None = None,
    min_confidence: float | None = None,
) -> list[dict[str, Any]]:
    clauses = ["run_id = ?", "repo_full_name = ?"]
    params: list[Any] = [run_id, repo_full_name]
    if tier is not None:
        clauses.append("tier = ?")
        params.append(tier)
    if min_confidence is not None:
        clauses.append("confidence >= ?")
        params.append(min_confidence)
    sql = (
        f"SELECT * FROM bulk_scan_findings WHERE {' AND '.join(clauses)} "  # noqa: S608
        f"ORDER BY confidence DESC"
    )
    rows = db._conn.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def get_surfaced_findings_ranked(db: UnifiedDatabase, run_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    sql = (
        "SELECT * FROM bulk_scan_findings "
        "WHERE run_id = ? AND surfaced = 1 "
        "ORDER BY confidence DESC, repo_full_name, id"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    rows = db._conn.execute(sql, (run_id,)).fetchall()
    return [dict(r) for r in rows]


def count_findings(db: UnifiedDatabase, run_id: str, surfaced: bool | None = None) -> int:
    if surfaced is None:
        sql = "SELECT COUNT(*) AS cnt FROM bulk_scan_findings WHERE run_id = ?"
        params: tuple[Any, ...] = (run_id,)
    else:
        sql = "SELECT COUNT(*) AS cnt FROM bulk_scan_findings WHERE run_id = ? AND surfaced = ?"
        params = (run_id, 1 if surfaced else 0)
    row = db._conn.execute(sql, params).fetchone()
    return int(row["cnt"]) if row else 0
