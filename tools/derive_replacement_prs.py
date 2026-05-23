"""Drain bulk_scan derived_candidate rows into PRs via N6 (#273).

The bulk-scan pipeline produces ``bulk_scan_findings`` rows where
``investigation_state='derived_candidate'`` carries the candidate URL it
found. The per-target pipeline (``ghla batch run``) submits PRs via N6
but only after re-scanning each repo from scratch. This tool is the
bridge: it reads unsurfaced derived_candidate rows, groups them by source
repo, and calls ``n6_submit_pr`` directly to fork+commit+PR with the
candidates we already have.

Usage::

    poetry run python tools/derive_replacement_prs.py
    poetry run python tools/derive_replacement_prs.py --dry-run
    poetry run python tools/derive_replacement_prs.py --auto-approve --max-prs 5
    poetry run python tools/derive_replacement_prs.py --method github_api_redirect
    poetry run python tools/derive_replacement_prs.py --repo owner/name
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

# #265 — eager-import the LinkDetective module chain so each module's
# setup_logging() call fires before the pipeline (or any silencing) runs.
from gh_link_auditor import (  # noqa: E402
    archive_client,  # noqa: F401
    github_resolver,  # noqa: F401
    link_detective,  # noqa: F401
    policy_checker,  # noqa: F401
    redirect_resolver,  # noqa: F401
)
from gh_link_auditor.metrics.models import PROutcome  # noqa: E402
from gh_link_auditor.pipeline.nodes.n6_submit_pr import n6_submit_pr  # noqa: E402
from gh_link_auditor.unified_db import DEFAULT_DB_PATH, UnifiedDatabase  # noqa: E402

# ---------------------------------------------------------------------------
# Pure-compute helpers (unit-testable, no I/O)
# ---------------------------------------------------------------------------


def _row_to_fix(row: dict) -> dict:
    """Build a FixPatch dict from a bulk_scan_findings row.

    N6's _apply_fixes uses str.replace on (source_file, original_url,
    replacement_url). The unified_diff field exists in the TypedDict but
    isn't consumed by N6 — empty string is fine.
    """
    return {
        "source_file": row["source_file"],
        "original_url": row["dead_url"],
        "replacement_url": row["candidate_url"],
        "unified_diff": "",
    }


def _row_to_verdict(row: dict) -> dict:
    """Build a Verdict dict for use in the PR body.

    ``pr_message.generate_pr_body_from_fixes`` looks up verdicts by
    (dead_link.url, dead_link.source_file). We synthesize a Verdict that
    matches our row so the PR body can include the same context.
    """
    return {
        "dead_link": {
            "url": row["dead_url"],
            "source_file": row["source_file"],
            "line_number": row["line_number"] or 0,
            "link_text": "",
            "http_status": None,
            "error_type": "",
        },
        "candidate": {
            "url": row["candidate_url"],
            "source": row["method"] or "",
            "title": None,
            "snippet": None,
            "tier": row["tier"] or 1,
        },
        "confidence": row["confidence"] if row["confidence"] is not None else 1.0,
        "reasoning": "",
        "approved": True,
    }


def _rows_to_fixes(rows: list[dict]) -> list[dict]:
    return [_row_to_fix(r) for r in rows]


def _rows_to_verdicts(rows: list[dict]) -> list[dict]:
    return [_row_to_verdict(r) for r in rows]


def _group_by_repo(rows: list[dict]) -> dict[str, list[dict]]:
    """Group rows by source repo (where the doc lives that we're fixing)."""
    by_repo: dict[str, list[dict]] = {}
    for r in rows:
        by_repo.setdefault(r["repo_full_name"], []).append(r)
    return by_repo


def _build_state(
    repo_full_name: str,
    fixes: list[dict],
    verdicts: list[dict],
    db_path: str,
    dry_run: bool,
) -> dict:
    """Synthesize a PipelineState dict for direct N6 invocation."""
    owner, _, name = repo_full_name.partition("/")
    return {
        "target": f"https://github.com/{repo_full_name}",
        "target_type": "url",
        "repo_owner": owner,
        "repo_name_short": name,
        "repo_name": repo_full_name,
        "fixes": fixes,
        "reviewed_verdicts": verdicts,
        "dry_run": dry_run,
        "db_path": db_path,
    }


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------


def _load_unsurfaced_candidates(
    udb: UnifiedDatabase,
    *,
    run_id: str | None = None,
    method: str | None = None,
    min_confidence: float | None = None,
    repo: str | None = None,
) -> list[dict]:
    """Load bulk_scan_findings rows ready for PR submission."""
    clauses = ["investigation_state = 'derived_candidate'", "surfaced = 0"]
    params: list[Any] = []
    if run_id:
        clauses.append("run_id = ?")
        params.append(run_id)
    if method:
        clauses.append("method = ?")
        params.append(method)
    if min_confidence is not None:
        clauses.append("confidence >= ?")
        params.append(min_confidence)
    if repo:
        clauses.append("repo_full_name = ?")
        params.append(repo)
    sql = (  # noqa: S608 — clauses are static identifiers, params are placeholders
        "SELECT * FROM bulk_scan_findings WHERE " + " AND ".join(clauses) + " ORDER BY repo_full_name, id"
    )
    rows = udb._conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _has_open_pr(udb: UnifiedDatabase, repo_full_name: str) -> bool:
    """True if a prior PR submission is still open for this repo."""
    row = udb._conn.execute(
        "SELECT 1 FROM pr_outcomes WHERE repo_full_name = ? AND status = 'open' LIMIT 1",
        (repo_full_name,),
    ).fetchone()
    return row is not None


def _mark_surfaced(udb: UnifiedDatabase, ids: list[int]) -> None:
    """Mark the named bulk_scan_findings rows as surfaced (already in a PR)."""
    if not ids:
        return
    placeholders = ",".join(["?"] * len(ids))
    udb._conn.execute(
        f"UPDATE bulk_scan_findings SET surfaced = 1 WHERE id IN ({placeholders})",  # noqa: S608
        ids,
    )
    udb._conn.commit()


def _record_pr_outcome(udb: UnifiedDatabase, repo_full_name: str, pr_url: str) -> None:
    """Record a freshly-submitted PR in the metrics DB so pr_tracker can find it."""
    outcome = PROutcome(
        repo_full_name=repo_full_name,
        pr_url=pr_url,
        submitted_at=datetime.now(timezone.utc),
        status="open",
    )
    udb.record_pr_outcome(outcome)


# ---------------------------------------------------------------------------
# Operator-facing preview + prompt
# ---------------------------------------------------------------------------


def _show_preview(repo_full_name: str, fixes: list[dict], rows: list[dict]) -> None:
    print(f"=== {repo_full_name} ({len(fixes)} fix{'es' if len(fixes) != 1 else ''}) ===")
    files = sorted({f["source_file"] for f in fixes})
    print(f"  files:    {', '.join(files)}")
    print("  fixes:")
    for row in rows:
        loc = row["source_file"]
        if row.get("line_number"):
            loc = f"{loc} line {row['line_number']}"
        print(f"    {loc}")
        print(f"      - {row['dead_url']}")
        print(f"      + {row['candidate_url']}")
        meta = []
        if row.get("method"):
            meta.append(row["method"])
        if row.get("confidence") is not None:
            meta.append(f"conf={row['confidence']:.2f}")
        if row.get("similarity_score") is not None:
            meta.append(f"sim={row['similarity_score']:.2f}")
        if row.get("verified_live"):
            meta.append("verified=1")
        if meta:
            print(f"      ({', '.join(meta)})")
    print()


def _prompt_yes_no_stop(input_fn: Any = input) -> str:
    """Return 'y' / 'n' / 's'. Re-prompts on invalid input."""
    while True:
        resp = input_fn("submit? [y/n/s] > ").strip().lower()
        if resp in ("y", "yes"):
            return "y"
        if resp in ("n", "no"):
            return "n"
        if resp in ("s", "stop", "x", "exit"):
            return "s"
        print("invalid response. enter y, n, or s.")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def derive_and_submit(
    args: argparse.Namespace,
    n6_fn: Any = None,
    input_fn: Any = input,
) -> dict:
    """Main orchestration. n6_fn / input_fn overrides for tests."""
    if n6_fn is None:
        n6_fn = n6_submit_pr

    submitted: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []
    errors: list[tuple[str, str]] = []

    with UnifiedDatabase(args.db) as udb:
        rows = _load_unsurfaced_candidates(
            udb,
            run_id=args.run_id,
            method=args.method,
            min_confidence=args.min_confidence,
            repo=args.repo,
        )
        repos = _group_by_repo(rows)

        for repo_full_name, repo_rows in repos.items():
            repo_url = f"https://github.com/{repo_full_name}"
            if udb.is_blacklisted(repo_url):
                skipped.append((repo_full_name, "blacklisted"))
                continue
            if _has_open_pr(udb, repo_full_name):
                skipped.append((repo_full_name, "open_pr_exists"))
                continue

            fixes = _rows_to_fixes(repo_rows)
            verdicts = _rows_to_verdicts(repo_rows)

            if args.dry_run:
                _show_preview(repo_full_name, fixes, repo_rows)
                print("[dry-run] would submit\n")
                skipped.append((repo_full_name, "dry_run"))
                continue

            if not args.auto_approve:
                _show_preview(repo_full_name, fixes, repo_rows)
                resp = _prompt_yes_no_stop(input_fn=input_fn)
                if resp == "n":
                    skipped.append((repo_full_name, "operator_declined"))
                    continue
                if resp == "s":
                    skipped.append((repo_full_name, "stop_requested"))
                    break

            state = _build_state(repo_full_name, fixes, verdicts, args.db, args.dry_run)
            try:
                state = n6_fn(state)
            except Exception as exc:
                errors.append((repo_full_name, f"{type(exc).__name__}: {exc}"))
                continue

            if state.get("errors"):
                errors.append((repo_full_name, "; ".join(state["errors"])))
                continue

            pr_url = state.get("pr_url", "")
            if not pr_url:
                errors.append((repo_full_name, "n6 returned no pr_url"))
                continue

            _record_pr_outcome(udb, repo_full_name, pr_url)
            _mark_surfaced(udb, [r["id"] for r in repo_rows])
            submitted.append((repo_full_name, pr_url))

            if len(submitted) >= args.max_prs:
                break

    return {"submitted": submitted, "skipped": skipped, "errors": errors}


def _print_summary(result: dict) -> None:
    print()
    print("=== summary ===")
    print(f"  submitted: {len(result['submitted'])}")
    for name, url in result["submitted"]:
        print(f"    {name}  {url}")
    print(f"  skipped:   {len(result['skipped'])}")
    for name, reason in result["skipped"]:
        print(f"    {name}  ({reason})")
    if result["errors"]:
        print(f"  errors:    {len(result['errors'])}")
        for name, err in result["errors"]:
            print(f"    {name}  {err}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Drain bulk_scan derived_candidates into PRs (#273)",
    )
    p.add_argument("--db", default=str(DEFAULT_DB_PATH), help="path to ghla.db")
    p.add_argument("--run-id", default=None, help="filter to one bulk-scan run_id")
    p.add_argument("--method", default=None, help="filter by candidate method")
    p.add_argument("--min-confidence", type=float, default=None)
    p.add_argument("--repo", default=None, help="single source repo filter (owner/name)")
    p.add_argument("--max-prs", type=int, default=10, help="safety cap (default 10)")
    p.add_argument("--auto-approve", action="store_true", help="skip per-repo prompt")
    p.add_argument("--dry-run", action="store_true", help="preview without forking")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = derive_and_submit(args)
    _print_summary(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
