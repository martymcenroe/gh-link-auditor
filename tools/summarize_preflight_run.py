"""Summarize a preflight run: verdict breakdown, hard-gate failure histogram,
top/bottom by score.

Reads JSON reports from ``data/preflight-reports/`` and prints headline
numbers. Useful right after a preflight batch finishes to characterize
what's passing/failing and why.

Usage::

    poetry run python tools/summarize_preflight_run.py [RUN_ID_PREFIX]

When ``RUN_ID_PREFIX`` is given (e.g. ``preflight-20260525T19``), only
reports whose filename begins with that prefix are summarized. This is
the common case after a re-run -- older reports stay in the directory
and you want to inspect just the latest batch.

Without a prefix, summarizes every report in the directory.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "data" / "preflight-reports"


def main() -> None:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        sys.stdout.write(__doc__ or "")
        return
    run_prefix = sys.argv[1] if len(sys.argv) > 1 else ""
    pattern = f"{run_prefix}*.json" if run_prefix else "*.json"
    paths = sorted(REPORTS.glob(pattern))
    sys.stdout.write(f"Pattern: {pattern}\nTotal JSON reports: {len(paths)}\n\n")

    reports = []
    for p in paths:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            reports.append(data)
        except json.JSONDecodeError as e:
            sys.stdout.write(f"  WARN: skipping malformed {p.name}: {e}\n")
            continue

    verdicts = Counter(r["verdict"] for r in reports)
    sys.stdout.write("--- Verdict breakdown ---\n")
    for v, n in verdicts.most_common():
        sys.stdout.write(f"  {v}: {n}\n")
    sys.stdout.write("\n")

    failed = [r for r in reports if r["verdict"] == "hard_gate_failed"]
    failure_gates = Counter(r.get("gate_failure_name") for r in failed)
    sys.stdout.write(f"--- Hard-gate failure histogram ({len(failed)} failures) ---\n")
    for g, n in failure_gates.most_common():
        sys.stdout.write(f"  {g}: {n}\n")
    sys.stdout.write("\n")

    passing = [r for r in reports if r["verdict"] == "pass"]
    passing_sorted = sorted(passing, key=lambda r: r["score"], reverse=True)
    sys.stdout.write(f"--- TOP 5 (by score, from {len(passing)} PASS) ---\n")
    for r in passing_sorted[:5]:
        sys.stdout.write(f"  score={r['score']} {r['repo_full_name']} -- {r['candidate'].get('dead_url', '')}\n")
    sys.stdout.write("\n")
    sys.stdout.write(f"--- BOTTOM 5 (by score, from {len(passing)} PASS) ---\n")
    for r in passing_sorted[-5:]:
        sys.stdout.write(f"  score={r['score']} {r['repo_full_name']} -- {r['candidate'].get('dead_url', '')}\n")
    sys.stdout.write("\n")

    low = sorted([r for r in reports if r["verdict"] == "score_too_low"], key=lambda r: r["score"])
    sys.stdout.write(f"--- TOP 3 SCORE_TOO_LOW (closest to threshold, n={len(low)}) ---\n")
    for r in low[-3:]:
        sys.stdout.write(f"  score={r['score']} {r['repo_full_name']}\n")
    sys.stdout.write(f"--- BOTTOM 3 SCORE_TOO_LOW (lowest, n={len(low)}) ---\n")
    for r in low[:3]:
        sys.stdout.write(f"  score={r['score']} {r['repo_full_name']}\n")
    sys.stdout.write("\n")

    needs_review = [r for r in reports if r["verdict"] == "needs_operator_review"]
    sys.stdout.write(f"--- NEEDS_OPERATOR_REVIEW ({len(needs_review)} reports) ---\n")
    for r in needs_review[:10]:
        sys.stdout.write(f"  {r['repo_full_name']} -- {r.get('gate_failure_name', '?')}\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
