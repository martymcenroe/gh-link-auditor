"""Per-candidate submission analysis (#403).

Reproduces the 2026-05-26 ad-hoc OasisLMF analysis as a repeatable artifact:
one document per candidate carrying everything needed to decide "submit or
not" without hand-stitching the DB row, the preflight report, live repo
metadata, the source line, and the maintainer's recent-PR profile.

Read-only by construction: gates and scores are lifted verbatim from the
preflight report, never re-evaluated.

**The agent never runs this.** It reads through the operator's ``gh`` auth;
an agent-driven run would place those bytes in an agent-owned process (the
ADR-0216 reasoning applies to reads as well as writes).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from gh_link_auditor.pipeline.pr_message import (
    generate_pr_body_from_fixes,
    generate_pr_title_from_fixes,
)
from gh_link_auditor.preflight._subproc import run_utf8

DEFAULT_REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "preflight-reports"
CONTEXT_LINES = 10
GH_TIMEOUT_S = 30


class CandidateNotFound(Exception):
    """No bulk_scan_findings row for the requested repo (+ run-id)."""


class PreflightReportNotFound(Exception):
    """No preflight report JSON on disk for the requested repo."""


class GitHubUnavailable(Exception):
    """A live GitHub read failed and --no-live was not requested."""


# ---------------------------------------------------------------------------
# Row mapping (moved here from tools/derive_replacement_prs.py so the PR
# section renders via the SAME mapping the submitter uses -- one shape, one
# parser. The tool keeps its private names as aliases.)
# ---------------------------------------------------------------------------


def row_to_fix(row: dict[str, Any]) -> dict[str, Any]:
    """Map a bulk_scan_findings row to a FixPatch-shaped dict."""
    return {
        "source_file": row.get("source_file") or "",
        "original_url": row.get("dead_url") or "",
        "replacement_url": row.get("candidate_url") or "",
        "unified_diff": "",
    }


def row_to_verdict(row: dict[str, Any]) -> dict[str, Any]:
    """Map a bulk_scan_findings row to a Verdict-shaped dict.

    ``pr_message.generate_pr_body_from_fixes`` looks up verdicts by
    (dead_link.url, dead_link.source_file); the remaining keys complete the
    Verdict shape. Field-for-field identical to what
    ``tools/derive_replacement_prs.py`` produced before this moved here, so
    generated PR bodies are unchanged.
    """
    return {
        "dead_link": {
            "url": row.get("dead_url") or "",
            "source_file": row.get("source_file") or "",
            "line_number": row.get("line_number") or 0,
            "link_text": "",
            "http_status": None,
            "error_type": "",
        },
        "candidate": {
            "url": row.get("candidate_url") or "",
            "source": row.get("method") or "",
            "title": None,
            "snippet": None,
            "tier": row.get("tier") or 1,
        },
        "confidence": row.get("confidence") if row.get("confidence") is not None else 1.0,
        "reasoning": "",
        "approved": True,
    }


# ---------------------------------------------------------------------------
# The mockable boundary: one facade for every live read this tool performs.
# ---------------------------------------------------------------------------


class GitHubFacade(Protocol):
    """Live-read surface. Tests substitute a fake; nothing mocks httpx."""

    def repo_metadata(self, owner: str, repo: str) -> dict[str, Any]: ...

    def file_content(self, owner: str, repo: str, path: str) -> str: ...

    def path_exists(self, owner: str, repo: str, path: str) -> bool: ...

    def merged_prs(self, owner: str, repo: str, limit: int) -> list[dict[str, Any]]: ...

    def open_prs(self, owner: str, repo: str, limit: int) -> list[dict[str, Any]]: ...


class RealGitHubFacade:
    """``gh``-backed facade. Same subprocess idiom as repo_quality."""

    def _gh_json(self, args: list[str]) -> Any:
        # run_utf8, not bare subprocess.run: Windows cp1252 would mangle
        # non-ASCII bytes in GitHub responses (repo descriptions, PR titles).
        result = run_utf8(["gh", *args], timeout=GH_TIMEOUT_S)
        if result.returncode != 0:
            raise GitHubUnavailable(f"gh {' '.join(args)} failed: {result.stderr.strip()[:200]}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubUnavailable(f"gh {' '.join(args)} returned non-JSON: {exc}") from exc

    def repo_metadata(self, owner: str, repo: str) -> dict[str, Any]:
        return self._gh_json(["api", f"repos/{owner}/{repo}"])

    def file_content(self, owner: str, repo: str, path: str) -> str:
        from gh_link_auditor.github_api import GitHubContentsClient

        client = GitHubContentsClient()
        try:
            return client.fetch_file_content(owner, repo, path)
        except Exception as exc:  # noqa: BLE001
            raise GitHubUnavailable(f"could not fetch {path}: {exc}") from exc
        finally:
            client.close()

    def path_exists(self, owner: str, repo: str, path: str) -> bool:
        result = run_utf8(["gh", "api", f"repos/{owner}/{repo}/contents/{path}"], timeout=GH_TIMEOUT_S)
        return result.returncode == 0

    def _pr_list(self, owner: str, repo: str, state: str, limit: int) -> list[dict[str, Any]]:
        return self._gh_json(
            [
                "pr",
                "list",
                "--repo",
                f"{owner}/{repo}",
                "--state",
                state,
                "--limit",
                str(limit),
                "--json",
                "number,title,author,createdAt,mergedAt,changedFiles,additions,deletions",
            ]
        )

    def merged_prs(self, owner: str, repo: str, limit: int) -> list[dict[str, Any]]:
        return self._pr_list(owner, repo, "merged", limit)

    def open_prs(self, owner: str, repo: str, limit: int) -> list[dict[str, Any]]:
        return self._pr_list(owner, repo, "open", limit)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

UNKNOWN = "(unknown — needs live)"

SECTION_KEYS = [
    "summary",
    "urls",
    "repo_metadata",
    "source_context",
    "edit_diff",
    "hard_gates",
    "score_breakdown",
    "maintainer_signals",
    "generated_pr",
    "risk_assessment",
    "submission_mechanics",
    "unknowns",
]


@dataclass
class CandidateAnalysis:
    """One field per spec section; both renderers read from this."""

    repo_full_name: str
    run_id: str
    report_path: Path | None
    summary: str = ""
    urls: list[dict[str, str]] = field(default_factory=list)
    repo_metadata: dict[str, Any] = field(default_factory=dict)
    source_context: dict[str, Any] = field(default_factory=dict)
    edit_diff: str = ""
    hard_gates: list[dict[str, Any]] = field(default_factory=list)
    score_breakdown: list[dict[str, Any]] = field(default_factory=list)
    maintainer_signals: dict[str, Any] = field(default_factory=dict)
    generated_pr: dict[str, str] = field(default_factory=dict)
    risk_assessment: dict[str, Any] = field(default_factory=dict)
    submission_mechanics: dict[str, str] = field(default_factory=dict)
    unknowns: list[str] = field(default_factory=list)


def find_candidate_row(db: Any, repo_full_name: str, run_id: str | None = None) -> dict[str, Any]:
    """Newest candidate row for the repo, optionally pinned to one run."""
    sql = (
        "SELECT * FROM bulk_scan_findings "
        "WHERE repo_full_name = ? AND candidate_url IS NOT NULL AND candidate_url != ''"
    )
    params: list[Any] = [repo_full_name]
    if run_id:
        sql += " AND run_id = ?"
        params.append(run_id)
    sql += " ORDER BY confidence DESC, id DESC LIMIT 1"
    row = db._conn.execute(sql, tuple(params)).fetchone()
    if row is None:
        scope = f" in run {run_id}" if run_id else ""
        raise CandidateNotFound(f"no candidate row for {repo_full_name}{scope}")
    return dict(row)


def find_preflight_report(reports_dir: Path | str, repo_full_name: str) -> Path:
    """Newest preflight JSON for the repo.

    Report stems are ``{preflight_run_id}-{owner}_{repo}`` — the preflight
    run id, not the bulk-scan run id — so matching is by repo + recency.
    """
    reports_dir = Path(reports_dir)
    safe = repo_full_name.replace("/", "_")
    matches = sorted(reports_dir.glob(f"*-{safe}.json")) if reports_dir.exists() else []
    if not matches:
        raise PreflightReportNotFound(f"no preflight report for {repo_full_name} under {reports_dir}")
    return matches[-1]


def _source_context(content: str, line_number: int) -> dict[str, Any]:
    """Lines around the target, clamped at file bounds, target marked."""
    lines = content.splitlines()
    if not lines:
        return {"available": False, "reason": "source file is empty", "lines": []}
    idx = max(1, min(line_number or 1, len(lines)))
    start = max(1, idx - CONTEXT_LINES)
    end = min(len(lines), idx + CONTEXT_LINES)
    rendered = []
    for n in range(start, end + 1):
        marker = f"  ← THIS LINE ({n})" if n == idx else ""
        rendered.append(f"{n:>5} | {lines[n - 1]}{marker}")
    return {"available": True, "start": start, "end": end, "target": idx, "lines": rendered}


def _style_notes(merged: list[dict[str, Any]]) -> list[str]:
    """Observations a human would make skimming recent merged PR titles."""
    if not merged:
        return ["no recent merged PRs to read style from"]
    titles = [p.get("title", "") for p in merged]
    lower = sum(1 for t in titles if t[:1].islower())
    conv = sum(1 for t in titles if ":" in t.split(" ")[0])
    bots = sum(1 for p in merged if str((p.get("author") or {}).get("login", "")).endswith("[bot]"))
    notes = [
        f"{lower}/{len(titles)} recent merged titles start lowercase",
        f"{conv}/{len(titles)} use a conventional-commits style prefix",
        f"{bots}/{len(merged)} recent merges are from bots",
    ]
    humans = [p for p in merged if not str((p.get("author") or {}).get("login", "")).endswith("[bot]")]
    logins = {str((p.get("author") or {}).get("login", "")) for p in humans}
    notes.append(
        f"{len(logins)} distinct human author(s) in the recent merge window: {', '.join(sorted(logins)) or 'none'}"
    )
    return notes


def _gate(gates: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for g in gates:
        if g.get("name") == name:
            return g
    return None


def _score(components: list[dict[str, Any]], cid: str) -> dict[str, Any] | None:
    for c in components:
        if c.get("name") == cid:
            return c
    return None


def _risk_from_gate(gates: list[dict[str, Any]], name: str, fail_level: str = "high") -> tuple[str, str]:
    g = _gate(gates, name)
    if g is None:
        return "unknown", f"gate `{name}` not evaluated"
    if g.get("passed"):
        return "none", g.get("reason", "")
    return fail_level, g.get("reason", "")


def _risk_from_score(components: list[dict[str, Any]], cid: str) -> tuple[str, str]:
    c = _score(components, cid)
    if c is None:
        return "unknown", f"component {cid} not scored"
    awarded, maximum = c.get("points_awarded", 0), c.get("max_points", 0) or 1
    reason = "; ".join(f"{k}={v}" for k, v in (c.get("evidence") or {}).items())
    if awarded >= maximum:
        return "none", reason
    if awarded > 0:
        return "low", reason
    return "high", reason


def _build_risk(gates: list[dict[str, Any]], components: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        ("Dead URL still genuinely dead", *_risk_from_gate(gates, "dead_url_still_dead")),
        ("Candidate URL actually alive", *_risk_from_gate(gates, "candidate_url_alive")),
        ("Wrong target (URL unrelated)", *_risk_from_gate(gates, "redirect_target_related")),
        ("Content equivalence (C5)", *_risk_from_score(components, "C5")),
        ("Duplicate PR already open", *_risk_from_gate(gates, "no_duplicate_pr")),
        ("README breaks from replacement", *_risk_from_gate(gates, "no_markdown_corruption")),
        ("Maintainer hostile to AI/bot PRs", *_risk_from_gate(gates, "anti_ai")),
        ("Star floor too low to bother", *_risk_from_gate(gates, "stars_floor", fail_level="low")),
        ("Maintainer inactive", *_risk_from_score(components, "R2")),
        ("Maintainer doesn't merge outsiders", *_risk_from_score(components, "R3")),
    ]
    levels = [level for _, level, _ in rows]
    if "high" in levels or "unknown" in levels:
        net = "hold"
    elif "low" in levels:
        net = "moderate"
    else:
        net = "as low as this campaign produces"
    return {
        "rows": [{"risk": r, "level": lv, "notes": nt} for r, lv, nt in rows],
        "net": net,
    }


def build_analysis(
    repo_full_name: str,
    db: Any,
    *,
    run_id: str | None = None,
    reports_dir: Path | str = DEFAULT_REPORTS_DIR,
    github: GitHubFacade | None = None,
    live: bool = True,
) -> CandidateAnalysis:
    """Assemble every section. Raises the module's three exceptions on failure."""
    row = find_candidate_row(db, repo_full_name, run_id)
    report_path = find_preflight_report(reports_dir, repo_full_name)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    owner, _, name = repo_full_name.partition("/")
    dead_url = row.get("dead_url") or ""
    candidate_url = row.get("candidate_url") or ""
    source_file = row.get("source_file") or ""
    line_number = row.get("line_number") or 0
    default_branch = "main"

    gates = report.get("gate_results", []) or []
    components = report.get("score_breakdown", []) or []

    analysis = CandidateAnalysis(
        repo_full_name=repo_full_name,
        run_id=row.get("run_id") or "",
        report_path=report_path,
    )

    # 3 / 4 / 8 need live reads.
    meta: dict[str, Any] = {}
    contributing_present: bool | None = None
    merged: list[dict[str, Any]] = []
    open_prs: list[dict[str, Any]] = []
    if live:
        if github is None:
            github = RealGitHubFacade()
        meta = github.repo_metadata(owner, name)
        default_branch = meta.get("default_branch") or default_branch
        contributing_present = github.path_exists(owner, name, "CONTRIBUTING.md")
        merged = github.merged_prs(owner, name, 8)
        open_prs = github.open_prs(owner, name, 5)
        try:
            content = github.file_content(owner, name, source_file)
            analysis.source_context = _source_context(content, line_number)
        except GitHubUnavailable as exc:
            analysis.source_context = {"available": False, "reason": str(exc), "lines": []}
    else:
        analysis.source_context = {"available": False, "reason": UNKNOWN, "lines": []}

    # 1 summary
    verdict = report.get("verdict", "unknown")
    score = report.get("score", 0)
    analysis.summary = (
        f"{repo_full_name} {source_file}:{line_number} — replace a dead docs URL with its live "
        f"replacement. {row.get('method') or 'unknown'} method, score {score}/100, verdict {verdict}."
    )

    # 2 URLs
    blob = f"https://github.com/{repo_full_name}/blob/{default_branch}/{source_file}"
    urls = [
        {"label": "Repo", "url": f"https://github.com/{repo_full_name}"},
        {"label": "Source file", "url": blob},
        {"label": "Exact line", "url": f"{blob}#L{line_number}"},
        {"label": "Maintainer", "url": f"https://github.com/{owner}"},
        {
            "label": "Open PRs",
            "url": f"https://github.com/{repo_full_name}/pulls?q=is%3Apr+is%3Aopen+sort%3Aupdated-desc",
        },
        {
            "label": "Merged PRs",
            "url": f"https://github.com/{repo_full_name}/pulls?q=is%3Apr+is%3Amerged+sort%3Aupdated-desc",
        },
        {"label": "Contributors", "url": f"https://github.com/{repo_full_name}/graphs/contributors"},
        {"label": "DEAD URL", "url": dead_url},
        {"label": "CANDIDATE URL", "url": candidate_url},
        {"label": "Preflight report (md)", "url": Path(str(report_path)[:-5] + ".md").as_uri()},
        {"label": "Preflight report (json)", "url": Path(report_path).as_uri()},
    ]
    if meta.get("license"):
        urls.append({"label": "License", "url": f"https://github.com/{repo_full_name}/blob/{default_branch}/LICENSE"})
    if contributing_present:
        urls.append(
            {
                "label": "CONTRIBUTING",
                "url": f"https://github.com/{repo_full_name}/blob/{default_branch}/CONTRIBUTING.md",
            }
        )
    redirect_gate = _gate(gates, "redirect_target_related")
    if redirect_gate and (redirect_gate.get("evidence") or {}).get("final_url"):
        urls.append({"label": "Redirect target", "url": redirect_gate["evidence"]["final_url"]})
    analysis.urls = urls

    # 3 repo metadata
    if live:
        lic = meta.get("license") or {}
        analysis.repo_metadata = {
            "Full name": meta.get("full_name", UNKNOWN),
            "Description": meta.get("description") or "(none)",
            "Primary language": meta.get("language") or "(none)",
            "License": (lic.get("spdx_id") if isinstance(lic, dict) else None) or "(none)",
            "Default branch": default_branch,
            "Stars": meta.get("stargazers_count", UNKNOWN),
            "Forks": meta.get("forks_count", UNKNOWN),
            "Watchers": meta.get("subscribers_count", UNKNOWN),
            "Open issues": meta.get("open_issues_count", UNKNOWN),
            "Owner type": (meta.get("owner") or {}).get("type", UNKNOWN),
            "Created": meta.get("created_at", UNKNOWN),
            "Last pushed": meta.get("pushed_at", UNKNOWN),
            "Archived": meta.get("archived", UNKNOWN),
            "Disabled": meta.get("disabled", UNKNOWN),
            "Fork": meta.get("fork", UNKNOWN),
        }
    else:
        analysis.repo_metadata = {k: UNKNOWN for k in ("Full name", "Stars", "License", "Last pushed", "Owner type")}

    # 5 edit diff
    analysis.edit_diff = (
        f"--- a/{source_file}\n"
        f"+++ b/{source_file}\n"
        f"@@ -{line_number},1 +{line_number},1 @@\n"
        f"-{dead_url}\n"
        f"+{candidate_url}"
    )

    # 6 / 7 lifted verbatim
    analysis.hard_gates = gates
    analysis.score_breakdown = components

    # 8 maintainer signals
    analysis.maintainer_signals = {
        "merged": merged,
        "open": open_prs,
        "style_notes": _style_notes(merged) if live else [UNKNOWN],
        "available": live,
    }

    # 9 the PR that would actually be filed
    fixes = [row_to_fix(row)]
    verdicts = [row_to_verdict(row)]
    analysis.generated_pr = {
        "title": generate_pr_title_from_fixes(fixes),
        "body": generate_pr_body_from_fixes(fixes, verdicts),
        "voice_notes": (
            "lowercase, no conventional-commits prefix, no bot self-attribution, "
            "no offer to revise or close; building-skill motivation + simple ask "
            "(see pr_message module docstring and the PR-body voice memory)"
        ),
    }

    # 10 risk
    analysis.risk_assessment = _build_risk(gates, components)

    # 11 mechanics
    run_flag = f" --run-id {analysis.run_id}" if analysis.run_id else ""
    analysis.submission_mechanics = {
        "command": (
            f"poetry run python tools/derive_replacement_prs.py{run_flag} "
            f"--repo {repo_full_name} --campaign-allowed --auto-approve --max-prs 1"
        ),
        "dry_run": (
            f"poetry run python tools/derive_replacement_prs.py{run_flag} "
            f"--repo {repo_full_name} --campaign-allowed --dry-run"
        ),
        "notes": (
            "Operator runs this, not the agent (ADR-0216). The classic-PAT pinentry "
            "prompt will appear; gpg-agent caching is set to 0 TTL so it prompts every "
            "run. Use the dry-run form to inspect the diff before committing to a PR."
        ),
    }

    # 12 unknowns
    unknowns = [
        "CLA bot requirements (not probed)",
        "PR template contents (not fetched)",
        "issue close-rate / responsiveness beyond the merged-PR window",
        "whether the maintainer has an AI-contribution policy outside README/CONTRIBUTING",
    ]
    if not live:
        unknowns.insert(0, "ALL live data (--no-live): repo metadata, source context, maintainer signals")
    analysis.unknowns = unknowns

    return analysis


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return out


def render_markdown(a: CandidateAnalysis) -> str:
    L: list[str] = [f"# Candidate Analysis — {a.repo_full_name}", ""]
    if a.report_path:
        L += [f"Preflight report: `{a.report_path.name}`", f"Bulk-scan run: `{a.run_id or 'n/a'}`", ""]

    L += ["## 1. Summary", "", a.summary, ""]

    L += ["## 2. URLs", ""]
    L += [f"- {u['label']}: <{u['url']}>" if u["url"] else f"- {u['label']}: (none)" for u in a.urls]
    L += [""]

    L += ["## 3. Repo metadata", ""]
    L += _md_table(["Field", "Value"], [[k, v] for k, v in a.repo_metadata.items()])
    L += [""]

    L += ["## 4. Source context", ""]
    if a.source_context.get("available"):
        L += ["```", *a.source_context["lines"], "```"]
    else:
        L += [f"_unavailable: {a.source_context.get('reason', 'unknown')}_"]
    L += [""]

    L += ["## 5. Exact edit", "", "```diff", a.edit_diff, "```", ""]

    L += ["## 6. Hard gates", ""]
    L += _md_table(
        ["#", "Gate", "Pass", "Reason", "Evidence"],
        [
            [
                str(i + 1),
                f"`{g.get('name', '')}`",
                "PASS" if g.get("passed") else "FAIL",
                g.get("reason", ""),
                "; ".join(f"{k}={v}" for k, v in (g.get("evidence") or {}).items()),
            ]
            for i, g in enumerate(a.hard_gates)
        ],
    )
    L += [""]

    L += ["## 7. Score breakdown", ""]
    total = sum(c.get("points_awarded", 0) for c in a.score_breakdown)
    L += _md_table(
        ["ID", "Points", "Max", "Evidence"],
        [
            [
                c.get("name", ""),
                str(c.get("points_awarded", 0)),
                str(c.get("max_points", 0)),
                "; ".join(f"{k}={v}" for k, v in (c.get("evidence") or {}).items()),
            ]
            for c in a.score_breakdown
        ]
        + [["**Total**", f"**{total}**", "**100**", ""]],
    )
    L += [""]

    L += ["## 8. Maintainer signals", ""]
    if a.maintainer_signals.get("available"):
        L += ["**Recent merged PRs**", ""]
        L += _md_table(
            ["PR", "Title", "Author", "Merged", "Files", "+/-"],
            [
                [
                    f"#{p.get('number', '?')}",
                    p.get("title", ""),
                    (p.get("author") or {}).get("login", "?"),
                    (p.get("mergedAt") or "")[:10],
                    str(p.get("changedFiles", "?")),
                    f"+{p.get('additions', '?')}/-{p.get('deletions', '?')}",
                ]
                for p in a.maintainer_signals.get("merged", [])
            ],
        )
        L += ["", "**Currently open PRs**", ""]
        L += _md_table(
            ["PR", "Title", "Author", "Created"],
            [
                [
                    f"#{p.get('number', '?')}",
                    p.get("title", ""),
                    (p.get("author") or {}).get("login", "?"),
                    (p.get("createdAt") or "")[:10],
                ]
                for p in a.maintainer_signals.get("open", [])
            ],
        )
        L += ["", "**Observed style**", ""]
        L += [f"- {n}" for n in a.maintainer_signals.get("style_notes", [])]
    else:
        L += [f"_unavailable: {UNKNOWN}_"]
    L += [""]

    L += ["## 9. The PR that would be filed", ""]
    L += [
        f"**Title:** {a.generated_pr.get('title', '')}",
        "",
        "**Body:**",
        "",
        "```",
        a.generated_pr.get("body", ""),
        "```",
        "",
    ]
    L += [f"_Voice notes: {a.generated_pr.get('voice_notes', '')}_", ""]

    L += ["## 10. Risk assessment", ""]
    L += _md_table(
        ["Risk", "Level", "Notes"],
        [[r["risk"], r["level"], r["notes"]] for r in a.risk_assessment.get("rows", [])],
    )
    L += ["", f"**Net risk: {a.risk_assessment.get('net', 'unknown')}**", ""]

    L += ["## 11. Submission mechanics", ""]
    L += ["```", a.submission_mechanics.get("command", ""), "```", ""]
    L += ["Dry run first:", "", "```", a.submission_mechanics.get("dry_run", ""), "```", ""]
    L += [a.submission_mechanics.get("notes", ""), ""]

    L += ["## 12. Still unknown / unfetched", ""]
    L += [f"- {u}" for u in a.unknowns]
    L += [""]

    return "\n".join(L)


def render_json(a: CandidateAnalysis) -> str:
    data = asdict(a)
    data["report_path"] = str(a.report_path) if a.report_path else None
    return json.dumps(data, indent=2, sort_keys=True, default=str)
