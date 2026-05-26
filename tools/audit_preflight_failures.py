"""Failure audit for any preflight batch.

For every report in ``data/preflight-reports/`` matching the run-id
prefix, the script:

- Extracts: repo, verdict, score, gate_failure_name, dead_url, candidate_url
- Computes normalized URL variants (strips CommonMark backslash escapes;
  adds/drops trailing slashes)
- Runs live HEAD-checks (with HEAD->GET fallback) against both the raw
  and normalized URLs in parallel
- Categorizes each case:

    A) ``A_CONFIRMED_FALSE_POSITIVE`` --recorded URL fails but the
       normalized form passes; preflight rejected something that's
       actually a valid fix
    B) ``B_SUSPECTED_FALSE_POSITIVE`` --URLs differ only in trailing
       slash or case; worth eyeballing
    C) ``C_REAL_FAILURE_<gate_or_score>`` --clean signal, URL legitimately
       rotted or candidate genuinely bad

Output: markdown report grouped by category at
``data/preflight-audit-YYYYMMDD.md``; CSV at the same path with ``.csv``
suffix for further analysis.

Usage::

    poetry run python tools/audit_preflight_failures.py [RUN_ID_PREFIX]

If ``RUN_ID_PREFIX`` is omitted, scans every report in the directory.

This is the tool that produced the findings driving #339, #340, #341,
#342, #343 from the #314 audit work.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "data" / "preflight-reports"

# Match a backslash followed by a CommonMark-significant char
ESCAPE_RE = re.compile(r"\\([(){}\[\]\\.\-+*_!#`|~<>=])")

# Track the small set of normalizations we want to test
NORMS = ["strip_escapes", "drop_trailing_slash", "add_trailing_slash"]


def normalize(url: str, kinds: list[str]) -> str:
    """Apply a chain of normalizations and return the result."""
    if not url:
        return ""
    out = url
    if "strip_escapes" in kinds:
        out = ESCAPE_RE.sub(r"\1", out)
    if "drop_trailing_slash" in kinds:
        if out.endswith("/") and out.count("/") > 3:  # don't drop the root /
            out = out[:-1]
    if "add_trailing_slash" in kinds:
        parsed = urlparse(out)
        # Only add slash if path is non-empty and has no trailing slash
        # and no query/fragment
        if parsed.path and not parsed.path.endswith("/") and not parsed.query and not parsed.fragment:
            out = urlunparse(parsed._replace(path=parsed.path + "/"))
    return out


def head_check(url: str, timeout: int = 10) -> dict[str, Any]:
    """HEAD-check (follow redirects) returning status_code or error."""
    if not url:
        return {"ok": False, "status_code": None, "error": "empty_url"}
    try:
        # Some servers (Wikipedia, others) return 403/405 on HEAD but 200 on GET.
        # Try HEAD first, fall back to GET on 4xx, never raise.
        ua = {"User-Agent": "Mozilla/5.0 ghla-audit"}
        r = requests.head(url, allow_redirects=True, timeout=timeout, headers=ua)
        if 400 <= r.status_code < 600:
            r = requests.get(url, allow_redirects=True, timeout=timeout, headers=ua, stream=True)
            try:
                next(r.iter_content(chunk_size=8))
            except StopIteration:
                pass
            finally:
                r.close()
        return {
            "ok": 200 <= r.status_code < 400,
            "status_code": r.status_code,
            "final_url": r.url,
            "error": None,
        }
    except requests.exceptions.RequestException as e:
        return {"ok": False, "status_code": None, "error": type(e).__name__}


@dataclass
class Case:
    file: str
    repo: str
    verdict: str
    score: int
    gate_failure: str | None
    dead_url: str
    dead_url_norm: str
    candidate_url: str
    candidate_url_norm: str
    source_file: str
    line_number: int | None
    # Live checks (filled in by ThreadPool)
    dead_raw_check: dict[str, Any] = field(default_factory=dict)
    dead_norm_check: dict[str, Any] = field(default_factory=dict)
    cand_raw_check: dict[str, Any] = field(default_factory=dict)
    cand_norm_check: dict[str, Any] = field(default_factory=dict)
    # Categorization
    category: str = ""
    notes: list[str] = field(default_factory=list)


def load_cases(run_prefix: str = "") -> list[Case]:
    cases: list[Case] = []
    pattern = f"{run_prefix}*.json" if run_prefix else "*.json"
    for p in sorted(REPORTS.glob(pattern)):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        cand = data.get("candidate", {})
        dead = cand.get("dead_url", "") or ""
        cand_url = cand.get("candidate_url", "") or ""
        dead_norm = normalize(dead, ["strip_escapes"])
        cand_norm = normalize(cand_url, ["strip_escapes"])
        cases.append(
            Case(
                file=p.name,
                repo=data["repo_full_name"],
                verdict=data["verdict"],
                score=data["score"],
                gate_failure=data.get("gate_failure_name"),
                dead_url=dead,
                dead_url_norm=dead_norm,
                candidate_url=cand_url,
                candidate_url_norm=cand_norm,
                source_file=cand.get("source_file", "") or "",
                line_number=cand.get("line_number"),
            )
        )
    return cases


def run_live_checks(cases: list[Case], max_workers: int = 12) -> None:
    """Live HEAD-check each URL variant for every case, in parallel."""
    work: list[tuple[Case, str, str]] = []
    for c in cases:
        work.append((c, "dead_raw_check", c.dead_url))
        if c.dead_url_norm != c.dead_url:
            work.append((c, "dead_norm_check", c.dead_url_norm))
        if c.candidate_url:
            work.append((c, "cand_raw_check", c.candidate_url))
            if c.candidate_url_norm != c.candidate_url and c.candidate_url_norm:
                work.append((c, "cand_norm_check", c.candidate_url_norm))

    sys.stdout.write(f"running {len(work)} live HEAD-checks (max {max_workers} parallel)\n")
    sys.stdout.flush()

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(head_check, url): (case, attr) for case, attr, url in work}
        done = 0
        for fut in as_completed(futures):
            case, attr = futures[fut]
            result = fut.result()
            setattr(case, attr, result)
            done += 1
            if done % 20 == 0:
                sys.stdout.write(f"  {done}/{len(work)} done\n")
                sys.stdout.flush()


def categorize(c: Case) -> None:
    """Assign a category + notes per case."""

    # Helpers
    def alive(r: dict[str, Any]) -> bool:
        return bool(r.get("ok"))

    def status(r: dict[str, Any]) -> str:
        if not r:
            return "n/a"
        s = r.get("status_code")
        return str(s) if s is not None else f"ERR:{r.get('error', '?')}"

    # Pre-checks
    dead_raw_alive = alive(c.dead_raw_check)
    dead_norm_alive = alive(c.dead_norm_check) if c.dead_url_norm != c.dead_url else dead_raw_alive
    cand_raw_alive = alive(c.cand_raw_check)
    cand_norm_alive = alive(c.cand_norm_check) if c.candidate_url_norm != c.candidate_url else cand_raw_alive

    # Detection-bug signals
    if c.dead_url_norm != c.dead_url:
        c.notes.append(
            f"dead_url has escape sequences (raw={status(c.dead_raw_check)}, norm={status(c.dead_norm_check)})"
        )
    if c.candidate_url and c.candidate_url_norm != c.candidate_url:
        c.notes.append(
            f"candidate_url has escape sequences (raw={status(c.cand_raw_check)}, norm={status(c.cand_norm_check)})"
        )
    if c.dead_url_norm and c.candidate_url_norm and c.dead_url_norm == c.candidate_url_norm:
        c.notes.append("dead_url and candidate_url are identical after normalization -- pure false positive")

    # Categorization
    if c.dead_url_norm and c.dead_url_norm == c.candidate_url_norm:
        c.category = "A_CONFIRMED_FALSE_POSITIVE"
        return

    # If the dead URL was reported dead but is actually alive when normalized, that's
    # a detection bug (dead-URL gate would no-op if rerun on normalized)
    if not dead_raw_alive and dead_norm_alive and c.dead_url_norm != c.dead_url:
        c.category = "A_CONFIRMED_FALSE_POSITIVE"
        c.notes.append("dead URL is alive after escape-normalization")
        return

    # If the candidate URL was reported dead but is alive when normalized, that's
    # also a detection bug --the candidate would be valid after we strip escapes
    if not cand_raw_alive and cand_norm_alive and c.candidate_url_norm != c.candidate_url:
        c.category = "A_CONFIRMED_FALSE_POSITIVE"
        c.notes.append("candidate URL is alive after escape-normalization")
        return

    # Very-similar URL pair --suspected false positive worth eyeballing
    if c.dead_url_norm and c.candidate_url_norm:
        # Levenshtein-ish: just compare normalized variants of common diff patterns
        if c.dead_url_norm.rstrip("/") == c.candidate_url_norm.rstrip("/"):
            c.notes.append("URLs differ only in trailing slash")
            c.category = "B_SUSPECTED_FALSE_POSITIVE"
            return
        if c.dead_url_norm.lower() == c.candidate_url_norm.lower():
            c.notes.append("URLs differ only in case")
            c.category = "B_SUSPECTED_FALSE_POSITIVE"
            return

    # Real failures from here on
    if c.verdict == "hard_gate_failed":
        c.category = f"C_REAL_FAILURE_{c.gate_failure}"
    elif c.verdict == "score_too_low":
        c.category = f"C_REAL_FAILURE_score_{c.score}"
    elif c.verdict == "pass":
        c.category = "PASS"
    else:
        c.category = f"C_REAL_FAILURE_{c.verdict}"


def render_markdown(cases: list[Case]) -> str:
    lines: list[str] = []
    lines.append("# Preflight Failure Audit --2026-05-25 re-run\n")
    lines.append(f"Total cases: {len(cases)}\n")

    by_cat: dict[str, list[Case]] = {}
    for c in cases:
        by_cat.setdefault(c.category, []).append(c)

    lines.append("## Category breakdown\n")
    lines.append("| Category | Count |\n|---|---:|\n")
    for cat, cs in sorted(by_cat.items()):
        lines.append(f"| {cat} | {len(cs)} |\n")
    lines.append("\n")

    for cat in sorted(by_cat):
        lines.append(f"## {cat} (n={len(by_cat[cat])})\n")
        for c in sorted(by_cat[cat], key=lambda x: x.repo):
            lines.append(f"### {c.repo}\n")
            lines.append(f"- File: `{c.source_file}` line {c.line_number}\n")
            lines.append(f"- Verdict: `{c.verdict}` | score={c.score} | failed_gate=`{c.gate_failure}`\n")
            dead_raw = c.dead_raw_check.get("status_code")
            lines.append(f"- Dead URL: `{c.dead_url}` (raw HEAD: {dead_raw})\n")
            if c.dead_url_norm != c.dead_url:
                dead_norm = c.dead_norm_check.get("status_code")
                lines.append(f"  - Normalized: `{c.dead_url_norm}` (norm HEAD: {dead_norm})\n")
            if c.candidate_url:
                cand_raw = c.cand_raw_check.get("status_code")
                lines.append(f"- Candidate URL: `{c.candidate_url}` (raw HEAD: {cand_raw})\n")
                if c.candidate_url_norm != c.candidate_url:
                    cand_norm = c.cand_norm_check.get("status_code")
                    lines.append(f"  - Normalized: `{c.candidate_url_norm}` (norm HEAD: {cand_norm})\n")
            if c.notes:
                lines.append("- Notes:\n")
                for n in c.notes:
                    lines.append(f"  - {n}\n")
            lines.append("\n")
    return "".join(lines)


def render_csv(cases: list[Case], out_csv: Path) -> None:
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "category",
                "repo",
                "verdict",
                "score",
                "gate_failure",
                "dead_url",
                "dead_url_norm",
                "dead_raw_status",
                "dead_norm_status",
                "candidate_url",
                "candidate_url_norm",
                "cand_raw_status",
                "cand_norm_status",
                "source_file",
                "line_number",
                "notes",
            ]
        )
        for c in cases:
            w.writerow(
                [
                    c.category,
                    c.repo,
                    c.verdict,
                    c.score,
                    c.gate_failure,
                    c.dead_url,
                    c.dead_url_norm,
                    c.dead_raw_check.get("status_code"),
                    c.dead_norm_check.get("status_code"),
                    c.candidate_url,
                    c.candidate_url_norm,
                    c.cand_raw_check.get("status_code"),
                    c.cand_norm_check.get("status_code"),
                    c.source_file,
                    c.line_number,
                    " | ".join(c.notes),
                ]
            )


def main() -> None:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        sys.stdout.write(__doc__ or "")
        return
    run_prefix = sys.argv[1] if len(sys.argv) > 1 else ""
    today = datetime.now().strftime("%Y%m%d")
    stem = f"preflight-audit-{today}"
    out_md = ROOT / "data" / f"{stem}.md"
    out_csv = ROOT / "data" / f"{stem}.csv"

    cases = load_cases(run_prefix=run_prefix)
    sys.stdout.write(f"loaded {len(cases)} cases (pattern={run_prefix or '*'})\n")
    sys.stdout.flush()

    run_live_checks(cases)
    for c in cases:
        categorize(c)

    md = render_markdown(cases)
    out_md.write_text(md, encoding="utf-8")
    render_csv(cases, out_csv)
    sys.stdout.write(f"\nMarkdown report: {out_md}\nCSV: {out_csv}\n")

    # Print category breakdown to stdout
    sys.stdout.write("\n=== Category breakdown ===\n")
    by_cat: dict[str, int] = {}
    for c in cases:
        by_cat[c.category] = by_cat.get(c.category, 0) + 1
    for cat, n in sorted(by_cat.items()):
        sys.stdout.write(f"  {cat}: {n}\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
