"""One-shot DB mutation: mark pending findings on known-anti-bot hosts as
skipped_alive so the running scan stops touching them on its next
iteration. Companion to the host-blocklist wire-in (false_positives.py
ALWAYS_ALIVE_DOMAINS additions, 2026-05-26).

Safe to run while a scan is active: updates only `pending` rows, doesn't
touch derived_candidate or any in-flight state. SQLite serializes.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

DOMAINS = {
    "npmjs.com",
    "kalshi.com",
    "polymarket.com",
    "medium.com",
    "openai.com",
    "linkedin.com",
    "dl.acm.org",
    "ieeexplore.ieee.org",
    "sciencedirect.com",
    "glyphwiki.org",
    "opendap.4tu.nl",
    "play.picoctf.org",
    "docs.signalfx.com",
    "forums.welltrainedmind.com",
    "experimentalhistory.substack.com",
    "gseth.com",
    "ecode360.com",
    "eigenphi.io",
    "notes.andymatuschak.org",
    "vision.princeton.edu",
    "afcd.foodstandards.gov.au",
    "bibliography.lingpy.org",
    "pyspedas.readthedocs.io",
    "mfa-models.readthedocs.io",
}


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "bulk-20260526T031148Z"
    db_path = Path.home() / ".ghla" / "ghla.db"
    d = sqlite3.connect(str(db_path))
    rows = d.execute(
        "SELECT id, dead_url FROM bulk_scan_findings WHERE run_id = ? AND investigation_state = 'pending'",
        (run_id,),
    ).fetchall()
    sys.stdout.write(f"pending rows in {run_id}: {len(rows)}\n")

    to_skip: list[int] = []
    for rid, url in rows:
        try:
            host = (urlparse(url).hostname or "").lower()
        except Exception:  # noqa: BLE001
            continue
        for dom in DOMAINS:
            if host == dom or host.endswith("." + dom):
                to_skip.append(rid)
                break

    sys.stdout.write(f"matching blocklist: {len(to_skip)}\n")
    if to_skip:
        placeholders = ",".join("?" * len(to_skip))
        d.execute(
            f"UPDATE bulk_scan_findings SET investigation_state='skipped_alive' WHERE id IN ({placeholders})",  # noqa: S608
            to_skip,
        )
        d.commit()
        sys.stdout.write(f"updated {len(to_skip)} rows to skipped_alive\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
