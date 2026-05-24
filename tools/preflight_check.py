"""Phase B preflight tool (#283 scaffold; full gates / scores land in
subsequent PRs under #281).

Runs the preflight evaluation for a single candidate (or all candidates
for a repo) and writes a markdown + JSON report. Used as a gate by
``tools/derive_replacement_prs.py`` PRIOR to ``n6_submit_pr`` so no fork
or push happens until preflight passes.

Usage::

    poetry run python tools/preflight_check.py --repo owner/name --report
    poetry run python tools/preflight_check.py --repo owner/name --score-only
    poetry run python tools/preflight_check.py --repo owner/name --strict
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from gh_link_auditor.preflight import (  # noqa: E402
    PreflightReport,
    PreflightVerdict,
    save_report,
)
from gh_link_auditor.preflight.gates import HARD_GATES  # noqa: E402

DEFAULT_REPORT_DIR = _PROJECT_ROOT / "data" / "preflight-reports"
DEFAULT_THRESHOLD = 90


def run_preflight(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any = None,  # UnifiedDatabase; typed loosely until gate/score PRs wire deps
    threshold: int = DEFAULT_THRESHOLD,
    run_id: str | None = None,
    skip_preflight_banner: bool = False,
    gates: list | None = None,
    score_components: list | None = None,
) -> PreflightReport:
    """Run preflight evaluation for a single candidate.

    Dispatches through every callable in ``HARD_GATES`` (PR-δ ships 7 non-
    subagent gates; PR-ε appends 3 subagent-using gates). Any failing
    gate short-circuits to ``HARD_GATE_FAILED``. If all gates pass and no
    score components are wired yet, returns ``PASS`` with ``score=threshold``
    so tool A's integration doesn't drop the candidate.

    Args:
        repo_full_name: ``owner/repo``.
        candidate: dict with at least ``dead_url`` and ``candidate_url``;
            may also carry ``source_file``, ``line_number``, ``method``,
            ``confidence``, etc.
        db: unified database (gates use cache tables from #285).
        threshold: minimum score required to PASS (default 90).
        run_id: optional caller-supplied run id; auto-generated if None.
        skip_preflight_banner: when True, the report markdown includes
            the BAD-ESCAPE banner (set by ``--skip-preflight`` on tool A).
        gates: optional override of the gate registry — defaults to
            ``HARD_GATES``. Tests inject empty / synthetic registries.
        score_components: optional override of the score registry —
            defaults to empty (PR-η / PR-θ will populate).

    Returns:
        A ``PreflightReport`` with the verdict + score + per-gate /
        per-score evidence.
    """
    now = datetime.now(timezone.utc).isoformat()
    gate_registry = HARD_GATES if gates is None else gates
    score_registry = [] if score_components is None else score_components

    gate_results = []
    gate_failure_name: str | None = None

    for gate_fn in gate_registry:
        result = gate_fn(repo_full_name, candidate, db)
        gate_results.append(result)
        if not result.passed:
            gate_failure_name = result.name
            return PreflightReport(
                repo_full_name=repo_full_name,
                candidate=dict(candidate),
                verdict=PreflightVerdict.HARD_GATE_FAILED,
                score=0,
                threshold=threshold,
                gate_results=gate_results,
                score_breakdown=[],
                gate_failure_name=gate_failure_name,
                started_at=now,
                completed_at=datetime.now(timezone.utc).isoformat(),
                run_id=run_id or _make_run_id(),
                skip_preflight_banner=skip_preflight_banner,
            )

    score_breakdown = []
    for score_fn in score_registry:
        sc = score_fn(repo_full_name, candidate, db)
        score_breakdown.append(sc)

    if score_breakdown:
        total = sum(sc.points_awarded for sc in score_breakdown)
        verdict = PreflightVerdict.PASS if total >= threshold else PreflightVerdict.SCORE_TOO_LOW
    else:
        # No score components wired yet (PR-η / PR-θ haven't landed) — return
        # score=threshold so tool A treats this as PASS (scaffold behavior).
        total = threshold
        verdict = PreflightVerdict.PASS

    return PreflightReport(
        repo_full_name=repo_full_name,
        candidate=dict(candidate),
        verdict=verdict,
        score=total,
        threshold=threshold,
        gate_results=gate_results,
        score_breakdown=score_breakdown,
        gate_failure_name=None,
        started_at=now,
        completed_at=datetime.now(timezone.utc).isoformat(),
        run_id=run_id or _make_run_id(),
        skip_preflight_banner=skip_preflight_banner,
    )


def _make_run_id() -> str:
    """Generate a sortable, unique-enough run id for a preflight invocation."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short = uuid.uuid4().hex[:6]
    return f"preflight-{ts}-{short}"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Phase B preflight evaluator (#281 umbrella)",
    )
    p.add_argument("--repo", required=True, help="target repo (owner/name)")
    p.add_argument("--candidate-id", default=None, help="optional candidate id filter")
    p.add_argument(
        "--report",
        action="store_true",
        help="write a markdown + JSON report to --preflight-log-dir",
    )
    p.add_argument(
        "--score-only",
        action="store_true",
        help="print only the integer score; useful for CI scripts",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero on any HARD_GATE_FAILED / SCORE_TOO_LOW / NEEDS_OPERATOR_REVIEW",
    )
    p.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_THRESHOLD,
        help="minimum total score required to PASS (default: 90)",
    )
    p.add_argument(
        "--preflight-log-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help=f"directory for markdown + JSON reports (default: {DEFAULT_REPORT_DIR})",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    candidate = {
        "dead_url": "",
        "candidate_url": "",
        "source_file": "",
        "line_number": None,
        "method": "",
    }
    report = run_preflight(
        repo_full_name=args.repo,
        candidate=candidate,
        threshold=args.threshold,
    )

    if args.report:
        md_path, json_path = save_report(report, args.preflight_log_dir)
        print(f"markdown: {md_path}")
        print(f"json: {json_path}")

    if args.score_only:
        print(report.score)
    else:
        print(f"verdict={report.verdict.value} score={report.score} threshold={report.threshold}")

    if args.strict and report.verdict != PreflightVerdict.PASS:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
