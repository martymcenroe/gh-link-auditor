"""Derive host-blocklist candidates from completed/partial bulk-scan telemetry.

Productionized version of ``tools/derive_host_blocklist.py``. Run at the
end of each bulk scan to surface hosts that consumed real investigation
budget and produced zero (or near-zero) tier-1 candidates. The output is
a markdown report at ``data/host-blocklist-candidates.md`` for operator
review -- this module does NOT mutate the static blocklist itself.

The audit (#258 / R4) explicitly forbids silent auto-addition. New
candidates must surface in the post-run report; the operator wires them
into ``ALWAYS_ALIVE_DOMAINS`` via a separate PR (see #366 for the
canonical pattern).

Filtering:

- Hosts already in ``false_positives.ALWAYS_ALIVE_DOMAINS`` are
  suppressed so the report only surfaces NEW candidates worth adding.
- ``real_investigations >= MIN_INVESTIGATIONS`` filters thin samples.
- ``tier1_yield_rate <= MAX_TIER1_YIELD_RATE`` selects zero-yield
  hosts.
- ``near_misses`` (yield in [1%, 5%]) are also surfaced for operator
  awareness.

Safe to run while Stage 3 is still draining (WAL mode + read-only).
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from gh_link_auditor.false_positives import ALWAYS_ALIVE_DOMAINS
from gh_link_auditor.unified_db import UnifiedDatabase

logger = logging.getLogger(__name__)

MIN_INVESTIGATIONS = 30
MAX_TIER1_YIELD_RATE = 0.01
NEAR_MISS_UPPER_BOUND = 0.05
SAMPLE_URLS_PER_HOST = 5
REPORT_PATH = Path("data/host-blocklist-candidates.md")


@dataclass
class HostStats:
    host: str
    total: int = 0
    unique_urls: int = 0
    alive: int = 0
    lang: int = 0
    no_cand: int = 0
    with_cand: int = 0
    pending: int = 0
    real: int = 0
    yield_rate: float = 0.0
    bot_signal_rate: float = 0.0
    wasted: int = 0
    top_status: list[tuple[int, int]] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)


def _host_of(url: str) -> str | None:
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc or None
    except Exception:
        return None


def _already_blocklisted(host: str) -> bool:
    """True if the host is already covered by ALWAYS_ALIVE_DOMAINS.

    Matches the suffix logic in ``is_always_alive_domain``: exact or
    ``*.domain`` match.
    """
    for domain in ALWAYS_ALIVE_DOMAINS:
        if host == domain or host.endswith(f".{domain}"):
            return True
    return False


def derive_blocklist_candidates(db: UnifiedDatabase, run_id: str) -> dict[str, list[HostStats]]:
    """Return per-bucket host statistics for the run.

    Buckets:

    - ``candidates`` -- hosts meeting the thresholds (recommended adds)
    - ``near_misses`` -- borderline hosts in the 1%-5% yield band
    - ``all`` -- every host with any real investigations (for diagnostics)

    Already-blocklisted hosts are filtered out from ``candidates`` and
    ``near_misses`` so the report surfaces only new actionable adds.
    """
    rows = db._conn.execute(
        """
        SELECT bsf.dead_url, bsf.investigation_state, bsf.method, ucc.http_status
        FROM bulk_scan_findings bsf
        LEFT JOIN url_check_cache ucc ON ucc.url = bsf.dead_url
        WHERE bsf.run_id = ?
        """,
        (run_id,),
    ).fetchall()

    host_state_counts: dict[str, Counter] = defaultdict(Counter)
    host_status_counts: dict[str, Counter] = defaultdict(Counter)
    host_sample_urls: dict[str, list[str]] = defaultdict(list)
    host_unique_urls: dict[str, set[str]] = defaultdict(set)

    for r in rows:
        url = r["dead_url"] or ""
        host = _host_of(url)
        if host is None:
            continue
        method = r["method"] or "pending"
        # method == 'pending' is a Stage 1 placeholder row. method != 'pending'
        # is a Stage-3 derived candidate (output, not input).
        if method != "pending":
            continue
        state = r["investigation_state"] or "pending"
        host_state_counts[host][state] += 1
        host_unique_urls[host].add(url)
        if r["http_status"] is not None:
            host_status_counts[host][int(r["http_status"])] += 1
        else:
            host_status_counts[host][-1] += 1
        if len(host_sample_urls[host]) < SAMPLE_URLS_PER_HOST and url not in host_sample_urls[host]:
            host_sample_urls[host].append(url)

    all_records: list[HostStats] = []
    for host, state_counts in host_state_counts.items():
        total = sum(state_counts.values())
        no_cand = state_counts.get("investigated_no_candidate", 0)
        with_cand = state_counts.get("investigated_with_candidate", 0)
        real = no_cand + with_cand
        yield_rate = (with_cand / real) if real > 0 else 0.0
        unique_with_status = sum(host_status_counts[host].values())
        if unique_with_status > 0:
            bot_signals = (
                host_status_counts[host].get(-1, 0)
                + host_status_counts[host].get(403, 0)
                + host_status_counts[host].get(429, 0)
                + host_status_counts[host].get(503, 0)
            )
            bot_signal_rate = bot_signals / unique_with_status
        else:
            bot_signal_rate = 0.0
        all_records.append(
            HostStats(
                host=host,
                total=total,
                unique_urls=len(host_unique_urls[host]),
                alive=state_counts.get("skipped_alive", 0),
                lang=state_counts.get("skipped_language", 0),
                no_cand=no_cand,
                with_cand=with_cand,
                pending=state_counts.get("pending", 0),
                real=real,
                yield_rate=yield_rate,
                bot_signal_rate=bot_signal_rate,
                wasted=real - with_cand,
                top_status=host_status_counts[host].most_common(4),
                samples=host_sample_urls[host],
            )
        )

    def _eligible(record: HostStats, upper_yield: float) -> bool:
        return (
            record.real >= MIN_INVESTIGATIONS
            and record.yield_rate <= upper_yield
            and not _already_blocklisted(record.host)
        )

    candidates = sorted(
        (r for r in all_records if _eligible(r, MAX_TIER1_YIELD_RATE)),
        key=lambda r: r.wasted,
        reverse=True,
    )
    near_misses = sorted(
        (r for r in all_records if _eligible(r, NEAR_MISS_UPPER_BOUND) and r.yield_rate > MAX_TIER1_YIELD_RATE),
        key=lambda r: r.wasted,
        reverse=True,
    )
    return {"candidates": candidates, "near_misses": near_misses, "all": all_records}


def render_candidates_markdown(
    buckets: dict[str, list[HostStats]],
    *,
    run_id: str,
    db_path: str,
    total_findings: int,
) -> str:
    """Markdown report for operator review. ASCII-safe (no em-dashes / arrows)."""
    candidates = buckets["candidates"]
    near_misses = buckets["near_misses"]
    all_records = buckets["all"]
    lines: list[str] = []
    lines.append(f"# Host blocklist candidates from `{run_id}`\n")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}\n")
    lines.append(f"Source DB: `{db_path}`\n")
    lines.append(f"Total findings considered: {total_findings:,}\n")
    lines.append(f"Distinct hosts found: {len(all_records):,}\n\n")
    lines.append("## Thresholds applied\n\n")
    lines.append(f"- `real_investigations >= {MIN_INVESTIGATIONS}`\n")
    lines.append(f"- `tier1_yield_rate <= {MAX_TIER1_YIELD_RATE:.1%}`\n")
    lines.append("- already-blocklisted hosts (ALWAYS_ALIVE_DOMAINS) are filtered out\n\n")
    lines.append("## Hosts recommended for blocklist\n\n")
    lines.append(f"**{len(candidates)} hosts**, ranked by wasted-investigation cost.\n\n")
    if not candidates:
        lines.append("_None met the thresholds for this run._\n\n")
    else:
        lines.append("| Host | Findings | Real | with_cand | Yield | Wasted | Bot% | Top statuses |\n")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---|\n")
        for r in candidates:
            top_status_str = ", ".join(f"{('None' if k == -1 else str(k))}:{v:,}" for k, v in r.top_status)
            lines.append(
                f"| `{r.host}` | {r.total:,} | {r.real:,} | "
                f"{r.with_cand:,} | {r.yield_rate:.2%} | {r.wasted:,} | "
                f"{r.bot_signal_rate:.0%} | {top_status_str} |\n"
            )
        lines.append("\n### Sample URLs per host (top 10 candidates)\n\n")
        for r in candidates[:10]:
            lines.append(
                f"**`{r.host}`** -- {r.total:,} findings, {r.real:,} investigated, "
                f"{r.with_cand:,} with candidate ({r.yield_rate:.2%})\n"
            )
            for u in r.samples:
                lines.append(f"- `{u}`\n")
            lines.append("\n")
    lines.append("## Near-miss hosts (1%-5% yield)\n\n")
    lines.append(f"**{len(near_misses)} hosts**. Borderline.\n\n")
    if near_misses:
        lines.append("| Host | Findings | Real | with_cand | Yield | Wasted | Bot% |\n")
        lines.append("|---|---:|---:|---:|---:|---:|---:|\n")
        for r in near_misses[:30]:
            lines.append(
                f"| `{r.host}` | {r.total:,} | {r.real:,} | "
                f"{r.with_cand:,} | {r.yield_rate:.2%} | {r.wasted:,} | "
                f"{r.bot_signal_rate:.0%} |\n"
            )
        lines.append("\n")
    lines.append("## How to use\n\n")
    lines.append("1. Review the recommended list and the sample URLs per host.\n")
    lines.append("2. Reject hosts that look like single-repo typos or operator-actionable bugs.\n")
    lines.append("3. Approved hosts go into `false_positives.ALWAYS_ALIVE_DOMAINS` via a focused PR.\n")
    lines.append("4. Add per-host tests in `tests/unit/test_false_positives.py::TestIsAlwaysAliveDomain`.\n")
    lines.append("5. The next bulk scan will skip these hosts entirely (Stage 1, 2, and 3).\n")
    return "".join(lines)


def write_candidates_report(
    db: UnifiedDatabase,
    run_id: str,
    *,
    db_path: str,
    out_path: Path = REPORT_PATH,
) -> Path:
    """Compute and write the markdown candidates report. Returns the path.

    Logs a single info-level banner with the count of new candidates so
    the operator sees the result inline with the rest of the run output.
    """
    buckets = derive_blocklist_candidates(db, run_id)
    total_findings = db._conn.execute(
        "SELECT COUNT(*) AS n FROM bulk_scan_findings WHERE run_id = ?",
        (run_id,),
    ).fetchone()["n"]
    body = render_candidates_markdown(
        buckets,
        run_id=run_id,
        db_path=db_path,
        total_findings=total_findings,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    n_cand = len(buckets["candidates"])
    n_near = len(buckets["near_misses"])
    logger.info(
        "host-blocklist-telemetry: %d new candidate(s), %d near-miss(es) -- review %s",
        n_cand,
        n_near,
        out_path,
    )
    return out_path


__all__ = [
    "MIN_INVESTIGATIONS",
    "MAX_TIER1_YIELD_RATE",
    "NEAR_MISS_UPPER_BOUND",
    "REPORT_PATH",
    "HostStats",
    "derive_blocklist_candidates",
    "render_candidates_markdown",
    "write_candidates_report",
]


# Suppress unused-import warning -- `Any` is intentionally reserved for
# extending HostStats with arbitrary metadata in a future revision.
_ = Any
