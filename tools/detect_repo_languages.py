"""One-shot enrichment: populate bulk_scan_repos.detected_language for a run (#238).

Iterates every repo in the given run that doesn't already have a detected
language, fetches its README via raw.githubusercontent.com, runs langdetect,
and writes the result back. Idempotent — re-running only processes the
still-NULL rows.

Usage:
    poetry run python tools/detect_repo_languages.py --run-id <run-id> [--workers 20]

Runtime: ~3 min for 7,500 repos at 20 workers (raw CDN is fast).
No GitHub API quota consumed.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from gh_link_auditor.bulk_scan.language import detect_repo_language
from gh_link_auditor.unified_db import DEFAULT_DB_PATH, UnifiedDatabase

logger = logging.getLogger(__name__)


def _detect_one(repo_full_name: str, client: httpx.Client) -> tuple[str, str | None]:
    return repo_full_name, detect_repo_language(repo_full_name, client=client)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-id", required=True, help="bulk-scan run_id to enrich")
    p.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    p.add_argument("--workers", type=int, default=20)
    p.add_argument("--batch", type=int, default=100, help="DB commit batch size")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    with UnifiedDatabase(args.db_path) as db:
        rows = db._conn.execute(
            "SELECT repo_full_name FROM bulk_scan_repos WHERE run_id = ? AND detected_language IS NULL",
            (args.run_id,),
        ).fetchall()
        repos = [r["repo_full_name"] for r in rows]
        if not repos:
            print(f"nothing to do: every repo in {args.run_id} already has a detected_language")
            return 0
        print(f"detecting language for {len(repos):,} repos in {args.run_id} ...")

        client = httpx.Client(
            headers={"User-Agent": "gh-link-auditor-lang"},
            timeout=15.0,
            follow_redirects=True,
        )
        t0 = time.monotonic()
        pending: list[tuple[str, str | None]] = []
        try:
            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                futures = {ex.submit(_detect_one, r, client): r for r in repos}
                done = 0
                for fut in as_completed(futures):
                    repo, lang = fut.result()
                    pending.append((lang, args.run_id, repo))
                    done += 1
                    if len(pending) >= args.batch:
                        db._conn.executemany(
                            "UPDATE bulk_scan_repos SET detected_language = ? WHERE run_id = ? AND repo_full_name = ?",
                            pending,
                        )
                        db._conn.commit()
                        pending.clear()
                    if done % 500 == 0:
                        rate = done / (time.monotonic() - t0)
                        print(f"  progress: {done:,}/{len(repos):,}  ({rate:.1f}/sec)")
            if pending:
                db._conn.executemany(
                    "UPDATE bulk_scan_repos SET detected_language = ? WHERE run_id = ? AND repo_full_name = ?",
                    pending,
                )
                db._conn.commit()
        finally:
            client.close()

        elapsed = time.monotonic() - t0
        print(f"done in {elapsed:.1f}s ({len(repos) / elapsed:.1f} repos/sec)")

        # Summary
        print("\nlanguage distribution:")
        for r in db._conn.execute(
            "SELECT COALESCE(detected_language, '(unknown)') as lang, COUNT(*) as n "
            "FROM bulk_scan_repos WHERE run_id = ? GROUP BY lang ORDER BY n DESC",
            (args.run_id,),
        ):
            print(f"  {r['lang']:12s} {r['n']:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
