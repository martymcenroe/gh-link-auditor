"""Preflight report data structures + renderers (#286).

Used by tools/preflight_check.py and by tests as the canonical shape of a
preflight run's output. Markdown is human-readable (operator clicks
through links to investigate); JSON is the same data, every dataclass
field serialized for downstream analytics + golden-file regression tests.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class PreflightVerdict(str, Enum):
    """Final verdict for a preflight run on a single candidate."""

    PASS = "pass"
    HARD_GATE_FAILED = "hard_gate_failed"
    NEEDS_OPERATOR_REVIEW = "needs_operator_review"
    SCORE_TOO_LOW = "score_too_low"


@dataclass
class GateResult:
    """Result of a single hard gate check."""

    name: str
    passed: bool
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreComponent:
    """Result of a single scored component."""

    name: str
    points_awarded: int
    max_points: int
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreflightReport:
    """Full preflight run report for a single candidate."""

    repo_full_name: str
    candidate: dict[str, Any]
    verdict: PreflightVerdict
    score: int = 0
    threshold: int = 90
    gate_results: list[GateResult] = field(default_factory=list)
    score_breakdown: list[ScoreComponent] = field(default_factory=list)
    gate_failure_name: str | None = None
    started_at: str = ""
    completed_at: str = ""
    run_id: str = ""
    skip_preflight_banner: bool = False

    def __post_init__(self) -> None:
        if not self.started_at:
            self.started_at = datetime.now(timezone.utc).isoformat()
        if not self.completed_at:
            self.completed_at = self.started_at


def _format_evidence(evidence: dict[str, Any]) -> str:
    if not evidence:
        return ""
    parts = [f"{k}={v}" for k, v in evidence.items()]
    return "; ".join(parts)


def render_markdown(report: PreflightReport) -> str:
    """Render a human-readable markdown report.

    Operator-clickable links section + per-gate evidence table + score
    breakdown + the OPERATOR REVIEW NEEDED banner when appropriate.
    """
    lines: list[str] = []

    owner_repo = report.repo_full_name
    candidate = report.candidate

    lines.append(f"# Preflight Report — {owner_repo}")
    lines.append("")
    lines.append(f"**Run ID:** `{report.run_id or 'n/a'}`")
    lines.append(f"**Started:** {report.started_at}")
    lines.append(f"**Completed:** {report.completed_at}")
    lines.append(f"**Verdict:** `{report.verdict.value}`")
    lines.append(f"**Score:** {report.score} / 100 (threshold: {report.threshold})")
    if report.gate_failure_name:
        lines.append(f"**Failed gate:** `{report.gate_failure_name}`")
    lines.append("")

    if report.verdict == PreflightVerdict.NEEDS_OPERATOR_REVIEW:
        lines.append("> ## OPERATOR REVIEW NEEDED")
        lines.append(">")
        lines.append(
            "> One or more checks returned an uncertain verdict that requires manual decision. "
            "Read the gate evidence below, then either add the repo to the blacklist "
            "(`ghla blacklist add <repo>`) and re-run preflight, or re-run with "
            "`--skip-preflight` to file the PR anyway (banner-warned)."
        )
        lines.append("")

    if report.skip_preflight_banner:
        lines.append("> ## SKIP-PREFLIGHT BANNER")
        lines.append(">")
        lines.append(
            "> This report was generated with `--skip-preflight`. The PR was filed without "
            "preflight gating. Treat findings below as advisory only."
        )
        lines.append("")

    lines.append("## Candidate")
    dead_url = candidate.get("dead_url", "")
    candidate_url = candidate.get("candidate_url", "")
    source = candidate.get("source_file", "")
    line_number = candidate.get("line_number", "")
    method = candidate.get("method", "")
    lines.append(f"- Dead URL: <{dead_url}>")
    lines.append(f"- Candidate URL: <{candidate_url}>")
    if source:
        suffix = f"#L{line_number}" if line_number else ""
        lines.append(f"- Source: `{source}{suffix}`")
    if method:
        lines.append(f"- Method: `{method}`")
    lines.append("")

    lines.append("## Hard gates")
    if report.gate_results:
        lines.append("")
        lines.append("| # | Name | Pass | Reason | Evidence |")
        lines.append("|---|------|------|--------|----------|")
        for idx, gate in enumerate(report.gate_results, start=1):
            evidence_str = _format_evidence(gate.evidence)
            pass_str = "YES" if gate.passed else "NO"
            lines.append(f"| {idx} | `{gate.name}` | {pass_str} | {gate.reason} | {evidence_str} |")
    else:
        lines.append("")
        lines.append("_No hard gates evaluated._")
    lines.append("")

    lines.append("## Score breakdown (correctness 75 + receptivity 25)")
    if report.score_breakdown:
        lines.append("")
        lines.append("| ID | Component | Points | Max | Evidence |")
        lines.append("|----|-----------|-------:|----:|----------|")
        for score in report.score_breakdown:
            evidence_str = _format_evidence(score.evidence)
            lines.append(
                f"| {score.name} | `{score.name}` | {score.points_awarded} | {score.max_points} | {evidence_str} |"
            )
        lines.append(f"| | **Total** | **{report.score}** | **100** | |")
    else:
        lines.append("")
        lines.append("_No scored components evaluated._")
    lines.append("")

    lines.append("## Operator-clickable links")
    owner, _, _ = owner_repo.partition("/")
    lines.append(f"- Maintainer profile: <https://github.com/{owner}>")
    lines.append(f"- Recent PRs: <https://github.com/{owner_repo}/pulls?q=is%3Apr+sort%3Aupdated-desc>")
    if dead_url:
        lines.append(f"- Dead URL: <{dead_url}>")
    if candidate_url:
        lines.append(f"- Candidate URL: <{candidate_url}>")
    lines.append("")

    return "\n".join(lines)


def render_json(report: PreflightReport) -> str:
    """Render the report as JSON (every dataclass field serialized)."""
    data = asdict(report)
    # Enum -> str
    data["verdict"] = report.verdict.value
    return json.dumps(data, indent=2, sort_keys=True, default=str)


def save_report(report: PreflightReport, log_dir: Path | str) -> tuple[Path, Path]:
    """Write markdown + JSON variants of the report to ``log_dir``.

    File names follow the pattern
    ``{run_id}-{owner}_{repo}.{md,json}`` so multiple candidates per run
    don't collide. Returns the two written paths.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_repo = report.repo_full_name.replace("/", "_")
    stem = f"{report.run_id or 'preflight'}-{safe_repo}"
    md_path = log_dir / f"{stem}.md"
    json_path = log_dir / f"{stem}.json"
    md_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(render_json(report), encoding="utf-8")
    return md_path, json_path
