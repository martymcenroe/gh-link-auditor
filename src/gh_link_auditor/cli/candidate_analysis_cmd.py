"""CLI for per-candidate submission analysis (#403).

``ghla candidate-analysis <owner/repo>`` — see LLD-403.

Exit codes (per the issue spec):
    0  analysis rendered
    1  no candidate row for repo (+ run-id)
    2  no preflight report on disk for repo
    3  a live GitHub read failed and --no-live was not passed
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gh_link_auditor.unified_db import DEFAULT_DB_PATH


def build_candidate_analysis_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the candidate-analysis subcommand."""
    p = subparsers.add_parser(
        "candidate-analysis",
        help="Full submission analysis for one candidate (#403)",
    )
    p.add_argument("repo", help="Candidate repo as owner/name")
    p.add_argument("--run-id", default=None, help="Pin to one bulk-scan run (default: best/newest candidate)")
    p.add_argument("--db", dest="db_path", default=str(DEFAULT_DB_PATH), help="Unified DB path")
    p.add_argument("--format", choices=["md", "json"], default="md")
    p.add_argument("--out", default=None, help="Write to this path instead of stdout")
    p.add_argument("--reports-dir", default=None, help="Preflight reports directory")
    p.add_argument(
        "--no-live",
        action="store_true",
        help="Skip all GitHub reads; render from DB + preflight report only",
    )
    p.set_defaults(func=cmd_candidate_analysis)


def cmd_candidate_analysis(args: argparse.Namespace) -> int:
    """Assemble and render the analysis. See module docstring for exit codes."""
    from gh_link_auditor.candidate_analysis import (
        DEFAULT_REPORTS_DIR,
        CandidateNotFound,
        GitHubUnavailable,
        PreflightReportNotFound,
        build_analysis,
        render_json,
        render_markdown,
    )
    from gh_link_auditor.unified_db import UnifiedDatabase

    reports_dir = Path(args.reports_dir) if args.reports_dir else DEFAULT_REPORTS_DIR

    try:
        with UnifiedDatabase(args.db_path) as db:
            analysis = build_analysis(
                args.repo,
                db,
                run_id=args.run_id,
                reports_dir=reports_dir,
                github=getattr(args, "github", None),
                live=not args.no_live,
            )
    except CandidateNotFound as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except PreflightReportNotFound as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except GitHubUnavailable as exc:
        print(f"ERROR: live GitHub read failed: {exc}", file=sys.stderr)
        print("Re-run with --no-live to render from DB + preflight report only.", file=sys.stderr)
        return 3

    body = render_json(analysis) if args.format == "json" else render_markdown(analysis)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")
        print(f"analysis written: {out.resolve()}")
    else:
        print(body)
    return 0
