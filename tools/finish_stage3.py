"""Standalone Stage 3 completion: investigate dead URLs in a bulk-scan run.

For ``bulk-20260514T042627Z`` this is the actual unfinished work — Stage 3
has never touched this run's ~440k pending findings. After Stage 2's cache
classification, roughly ~321k of those URLs are alive (skip path), ~16-30k
have non-English source-repo docs (skip path once ``detect_languages.py``
finishes), and the remaining ~60k actually-dead URLs need investigation.

Design rules (the same ones the user spelled out, no exceptions):

* **No quality stop-loss.** This program does not abort itself based on
  finding quality. It runs until everything is processed or the operator
  signals shutdown.
* **No DELETE.** Per LLD-244 the Stage 1 placeholder row stays; we just
  flip its ``investigation_state`` and insert derived-candidate rows when
  the investigation surfaces tier-1 candidates.
* **Atomic per-finding transaction.** ``UPDATE investigation_state`` and
  any candidate ``INSERT``s land in the same SQLite transaction; a crash
  mid-finding rolls back so the finding stays ``'pending'`` for retry.
* **Parallel investigations.** ``investigate_one`` creates a fresh
  ``LinkDetective`` per call (zero shared state), so a thread pool is safe.
  Default 8 workers; configurable.
* **Pre-loaded language + liveness maps.** Stage 3 makes no DB call inside
  the per-finding loop except for the atomic write. Language and liveness
  come from in-memory dicts populated once at startup.

Concurrency: SAFE to run while ``finish_stage1.py``, ``finish_stage2.py``,
or ``detect_languages.py`` are running on the same DB. Does NOT take the
bulk-scan lock. Writes only to the ``bulk_scan_findings`` rows we own (one
per ``id``); inserts new candidate rows. SQLite serializes any actual
write collision and Python ``threading.Lock`` guards stat updates.

Rate limiting: per-investigation HTTP calls (Wikipedia API, GitHub API,
liveness-verify HEAD) are made inside ``LinkDetective`` which has its own
retry policies for those clients. We don't add an outer escalation here
because failure modes are heterogeneous (one host throttling vs. broad
network issue) and silenced inside LinkDetective. We DO surface an
anomaly signal: if the "no candidate" rate over the recent window
spikes above 95%, the status line flags it loudly so the operator can
investigate. Rate of false-zero results = best proxy we have without
rewriting LinkDetective's exception surface.

Observability: status line every 60s with state-bucket breakdown.

Usage::

    poetry run python tools/finish_stage3.py
    poetry run python tools/finish_stage3.py --workers 16
    poetry run python tools/finish_stage3.py --run-id <other-run>
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sqlite3
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Match pyproject's [tool.pytest.ini_options] pythonpath = [".", "src"] —
# LinkDetective's transitive imports use `from src.logging_config import ...`
# (a pre-packaging path style). Without the project root on sys.path, every
# LinkDetective construction raises ModuleNotFoundError and investigate_one
# swallows it as "no candidate". Hotfix until the broken imports are migrated
# to `from gh_link_auditor.logging_config import ...`.
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

# #265 — eager-import the LinkDetective module chain so each module's
# setup_logging() call (which sets logger.level=INFO and adds a handler)
# fires BEFORE main()'s setLevel(ERROR) loop. Without these, investigate_one
# lazy-imports them in worker threads AFTER the silencing has already run on
# loggers that had no handlers yet — setup_logging then resets them to INFO
# and the operator console fills with archive_client CDX warnings.
from gh_link_auditor import (  # noqa: E402
    archive_client,  # noqa: F401
    github_resolver,  # noqa: F401
    link_detective,  # noqa: F401
    policy_checker,  # noqa: F401
    redirect_resolver,  # noqa: F401
)
from gh_link_auditor.bulk_scan import investigation  # noqa: E402
from gh_link_auditor.bulk_scan.config import INCLUDE_LANGUAGES  # noqa: E402
from gh_link_auditor.bulk_scan.host_blocklist import is_blocklisted_host  # noqa: E402
from gh_link_auditor.unified_db import UnifiedDatabase  # noqa: E402

DEFAULT_RUN_ID = "bulk-20260514T042627Z"
STATUS_FILE = _PROJECT_ROOT / "data" / "finish-stage3-status.txt"
LOG_INTERVAL_S = 60
DEFAULT_WORKERS = 8
# "No candidate rate is anomalously high" alarm — surfaced on the status
# line, does not pause the program. 95% means: of the last 500 actual
# investigations, ≥475 produced zero candidates. That's not impossible on
# truly junk corpora but is the strongest single signal that a needed
# upstream (GH API, Wikipedia, network) is silently failing.
ANOMALY_WINDOW = 500
ANOMALY_THRESHOLD = 0.95


# ---------------------------------------------------------------------------


@dataclass
class Stats:
    started_monotonic: float = field(default_factory=time.monotonic)
    total: int = 0
    skipped_blocklist: int = 0
    skipped_language: int = 0
    skipped_alive: int = 0
    investigated_no_cand: int = 0
    investigated_with_cand: int = 0
    candidates_inserted: int = 0
    errors: int = 0
    # Track the no-candidate ratio over a rolling window of REAL investigations
    # (excluding skip paths). True = no candidate; False = candidate found.
    recent_no_cand: deque = field(default_factory=lambda: deque(maxlen=ANOMALY_WINDOW))
    last_url: str = ""
    last_outcome: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)
    # #270 — monotonic timestamp of the last `investigated_with_candidate`
    # event. None until the first candidate surfaces. Used by render_line
    # to show "time since last candidate" so the operator can tell whether
    # the pipeline has gone quiet vs. is still producing.
    last_cand_monotonic: float | None = None
    # #269 — rolling (monotonic_ts, processed_count) samples for a 5-minute
    # recent rate. status_emitter appends one entry per LOG_INTERVAL_S tick
    # before rendering. maxlen=5 ⇒ up to ~5 minutes of history.
    rate_window: deque = field(default_factory=lambda: deque(maxlen=5))

    def processed(self) -> int:
        return (
            self.skipped_blocklist
            + self.skipped_language
            + self.skipped_alive
            + self.investigated_no_cand
            + self.investigated_with_cand
            + self.errors
        )

    def remaining(self) -> int:
        return max(0, self.total - self.processed())

    def investigated(self) -> int:
        """Real investigations (excludes skip paths)."""
        return self.investigated_no_cand + self.investigated_with_cand

    def skipped(self) -> int:
        """All skip paths summed (alive + language + blocklist)."""
        return self.skipped_alive + self.skipped_language + self.skipped_blocklist

    def yield_pct(self) -> float:
        """Tier-1 yield as a percentage. Undefined when no real investigations."""
        n = self.investigated()
        if n == 0:
            return 0.0
        return 100.0 * self.investigated_with_cand / n

    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_monotonic

    def per_min(self) -> float:
        e = self.elapsed_s()
        if e <= 0 or self.processed() == 0:
            return 0.0
        return self.processed() / (e / 60.0)

    def recent_rate_per_min(self) -> float:
        """#269 — per-minute rate over the rate_window (last ~5 min)."""
        if len(self.rate_window) < 2:
            return self.per_min()
        ts0, p0 = self.rate_window[0]
        ts1, p1 = self.rate_window[-1]
        dt = ts1 - ts0
        if dt <= 0:
            return self.per_min()
        return (p1 - p0) / (dt / 60.0)

    def record_rate_sample(self) -> None:
        """Called by status_emitter once per tick before rendering."""
        self.rate_window.append((time.monotonic(), self.processed()))

    def eta_str(self) -> str:
        rate = self.per_min()
        if rate <= 0:
            return "?"
        m = self.remaining() / rate
        return f"{m:.0f}m" if m < 60 else f"{m / 60:.1f}h"

    def time_since_last_cand_str(self) -> str:
        """#270 — formatted '8m' / '12s' / '1.2h' or 'never' when never."""
        if self.last_cand_monotonic is None:
            return "never"
        delta = time.monotonic() - self.last_cand_monotonic
        if delta < 60:
            return f"{delta:.0f}s"
        if delta < 3600:
            return f"{delta / 60:.0f}m"
        return f"{delta / 3600:.1f}h"

    def no_cand_rate(self) -> float:
        """Fraction of recent REAL investigations that produced zero candidates."""
        if not self.recent_no_cand:
            return 0.0
        return sum(self.recent_no_cand) / len(self.recent_no_cand)

    def anomaly_flag(self) -> str:
        if len(self.recent_no_cand) >= ANOMALY_WINDOW and self.no_cand_rate() >= ANOMALY_THRESHOLD:
            return f" !ANOMALY no-cand-rate={100 * self.no_cand_rate():.0f}%"
        return ""

    def render_line(self) -> str:
        now = datetime.now().strftime("%H:%M:%S")
        pct = (100.0 * self.processed() / self.total) if self.total else 0.0
        invs = self.investigated()
        yield_str = f"yield={self.yield_pct():.1f}%" if invs else "yield=n/a"
        return (
            f"[{now}] stage3 {self.processed():,}/{self.total:,} ({pct:.1f}%) "
            f"skipped={self.skipped():,} investigated={invs:,} {yield_str} "
            f"cands+={self.candidates_inserted:,} "
            f"rate={self.per_min():.0f}/min (5m: {self.recent_rate_per_min():.0f}/min) "
            f"ETA={self.eta_str()} last_cand={self.time_since_last_cand_str()}"
            f"{self.anomaly_flag()}"
        )


# ---------------------------------------------------------------------------


class GracefulShutdown:
    def __init__(self) -> None:
        self.requested = False
        signal.signal(signal.SIGINT, self._handler)
        try:
            signal.signal(signal.SIGTERM, self._handler)
        except (AttributeError, ValueError):
            pass

    def _handler(self, signum: int, frame: object) -> None:  # noqa: ARG002
        self.requested = True
        sys.stdout.write(f"\n[!] shutdown signal {signum} — letting in-flight investigations drain\n")
        sys.stdout.flush()


def write_status_file(stats: Stats, run_id: str, *, final: bool = False) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if stats.last_cand_monotonic is None:
        sec_since_cand = ""
    else:
        sec_since_cand = f"{time.monotonic() - stats.last_cand_monotonic:.0f}"
    body = [
        f"run_id: {run_id}",
        f"status: {'finished' if final else 'running'}",
        f"started: {datetime.fromtimestamp(time.time() - stats.elapsed_s(), tz=timezone.utc).isoformat()}",
        f"now: {datetime.now(timezone.utc).isoformat()}",
        f"elapsed_min: {stats.elapsed_s() / 60:.1f}",
        f"total: {stats.total}",
        f"processed: {stats.processed()}",
        f"remaining: {stats.remaining()}",
        f"rate_per_min: {stats.per_min():.1f}",
        f"recent_rate_per_min: {stats.recent_rate_per_min():.1f}",
        f"eta: {stats.eta_str()}",
        f"skipped_alive: {stats.skipped_alive}",
        f"skipped_language: {stats.skipped_language}",
        f"skipped_blocklist: {stats.skipped_blocklist}",
        f"skipped_total: {stats.skipped()}",
        f"investigated_no_candidate: {stats.investigated_no_cand}",
        f"investigated_with_candidate: {stats.investigated_with_cand}",
        f"investigated_total: {stats.investigated()}",
        f"yield_pct: {stats.yield_pct():.2f}",
        f"candidates_inserted: {stats.candidates_inserted}",
        f"errors: {stats.errors}",
        f"recent_no_cand_rate: {100 * stats.no_cand_rate():.1f}%",
        f"anomaly: {bool(stats.anomaly_flag())}",
        f"seconds_since_last_candidate: {sec_since_cand}",
        f"last_url: {stats.last_url}",
        f"last_outcome: {stats.last_outcome}",
    ]
    STATUS_FILE.write_text("\n".join(body) + "\n", encoding="utf-8")


def status_emitter(stats: Stats, run_id: str, shutdown: GracefulShutdown) -> None:
    last = 0.0
    while not shutdown.requested:
        now = time.monotonic()
        if now - last >= LOG_INTERVAL_S:
            # #269 — sample BEFORE rendering so recent_rate uses the latest point.
            stats.record_rate_sample()
            sys.stdout.write(stats.render_line() + "\n")
            sys.stdout.flush()
            write_status_file(stats, run_id)
            last = now
        time.sleep(1)


# ---------------------------------------------------------------------------


def load_repo_languages(db: UnifiedDatabase, run_id: str) -> dict[str, str | None]:
    rows = db._conn.execute(
        "SELECT repo_full_name, detected_language FROM bulk_scan_repos WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    return {r["repo_full_name"]: r["detected_language"] for r in rows}


def language_excluded(detected: str | None) -> bool:
    """Return True if the repo should be skipped because of language.

    Matches the existing ``runner._is_repo_language_included`` semantics:
    NULL and 'unknown' pass through to investigation; any other non-en
    code is excluded.
    """
    if detected is None or detected == "unknown":
        return False
    return detected not in INCLUDE_LANGUAGES


def load_findings_with_liveness(
    db: UnifiedDatabase,
    run_id: str,
) -> list[dict]:
    """Snapshot all pending findings + their cached liveness in one query."""
    rows = db._conn.execute(
        """
        SELECT bsf.id, bsf.repo_full_name, bsf.source_file, bsf.line_number,
               bsf.dead_url, ucc.http_status
        FROM bulk_scan_findings bsf
        LEFT JOIN url_check_cache ucc ON ucc.url = bsf.dead_url
        WHERE bsf.run_id = ?
          AND bsf.method = 'pending'
          AND bsf.investigation_state = 'pending'
        """,
        (run_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def is_alive_status(code: int | None) -> bool:
    """200-399 = alive. NULL (never probed) = NOT alive (we investigate)."""
    return code is not None and 200 <= code < 400


# ---------------------------------------------------------------------------


def compute_outcome(
    finding: dict,
    repo_languages: dict[str, str | None],
) -> tuple[str, list[dict]]:
    """Pure compute — returns (state_label, candidates).

    Runs in a worker thread. NO DB I/O. The sqlite3 module raises
    ProgrammingError if a connection is used from any thread other than
    the one that created it (default ``check_same_thread=True``), so all
    DB writes are done in the main thread by ``write_outcome``.

    Returns one of:
        ('skipped_language', [])
        ('skipped_alive', [])
        ('investigated_no_candidate', [])
        ('investigated_with_candidate', [<tier1 candidates>])
        ('error', [])
    """
    repo = finding["repo_full_name"]
    url = finding["dead_url"]
    code = finding["http_status"]

    # #258 — skip hosts on the static blocklist before any other check.
    # Stage 3 wastes no cycles re-investigating anti-bot walls or
    # browser-verified-broken hosts. Findings remain in the DB; the
    # removal-PR derivation pass uses them downstream where applicable.
    if is_blocklisted_host(url):
        return ("skipped_blocklist", [])
    if language_excluded(repo_languages.get(repo)):
        return ("skipped_language", [])
    if is_alive_status(code):
        return ("skipped_alive", [])
    try:
        candidates = investigation.investigate_one(url, code if code is not None else "error")
        tier1 = investigation.filter_tier1(candidates)
    except Exception:
        return ("error", [])
    if not tier1:
        return ("investigated_no_candidate", [])
    return ("investigated_with_candidate", tier1)


def write_outcome(
    db: UnifiedDatabase,
    run_id: str,
    finding: dict,
    state: str,
    candidates: list[dict],
    stats: Stats,
) -> None:
    """Apply one finding's outcome to the DB. Runs in the main thread only.

    Atomic transaction: state UPDATE + any candidate INSERTs land together
    so a crash mid-write rolls back to leave the finding 'pending' for retry.
    """
    fid = finding["id"]
    repo = finding["repo_full_name"]
    url = finding["dead_url"]
    now_iso = datetime.now(timezone.utc).isoformat()

    if state == "error":
        stats.errors += 1
        stats.last_url = url
        stats.last_outcome = "error"
        return

    inserted = 0
    with db._conn:
        db._conn.execute(
            "UPDATE bulk_scan_findings SET investigation_state = ?, "
            "investigation_completed_at = ?, "
            "investigation_attempts = investigation_attempts + 1 "
            "WHERE id = ?",
            (state, now_iso, fid),
        )
        for c in candidates:
            conf = investigation.compute_confidence(c)
            db._conn.execute(
                "INSERT INTO bulk_scan_findings "
                "(run_id, repo_full_name, source_file, line_number, dead_url, "
                " candidate_url, method, tier, similarity_score, verified_live, "
                " confidence, surfaced, created_at, investigation_state) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'derived_candidate')",
                (
                    run_id,
                    repo,
                    finding["source_file"],
                    finding["line_number"],
                    url,
                    c["candidate_url"],
                    c["method"],
                    c["tier"],
                    c["similarity_score"],
                    1 if c.get("verified_live") else 0,
                    conf,
                    now_iso,
                ),
            )
            inserted += 1

    # Stats update — single-threaded already, but the lock is cheap and
    # protects against any future change that adds a second writer.
    with stats.lock:
        if state == "skipped_blocklist":
            stats.skipped_blocklist += 1
        elif state == "skipped_language":
            stats.skipped_language += 1
        elif state == "skipped_alive":
            stats.skipped_alive += 1
        elif state == "investigated_no_candidate":
            stats.investigated_no_cand += 1
            stats.recent_no_cand.append(True)
        elif state == "investigated_with_candidate":
            stats.investigated_with_cand += 1
            stats.candidates_inserted += inserted
            stats.recent_no_cand.append(False)
            # #270 — stamp the time of this candidate so render_line can show
            # "minutes since last candidate" for operator's pipeline-alive check.
            stats.last_cand_monotonic = time.monotonic()
        stats.last_url = url
        stats.last_outcome = state


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Stage 3 (investigation) for a bulk-scan run.")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument(
        "--db",
        default=str(Path.home() / ".ghla" / "ghla.db"),
        help="path to ghla.db (default: ~/.ghla/ghla.db)",
    )
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress per-minute status lines (status file still updates)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s :: %(message)s",
        force=True,
    )
    # Silence verbose modules. The LinkDetective modules emit WARNING-level
    # noise for normal-background events (Wayback CDX timeouts, GitHub 403s
    # that are retried internally, etc.) — they drown out the once-per-minute
    # status line. Bump to ERROR. #256 tracks the deeper handler-dedup fix.
    for noisy in (
        "httpx",
        "httpcore",
        "urllib3",
        "archive_client",
        "github_resolver",
        "link_detective",
        "redirect_resolver",
        "policy_checker",
    ):
        logging.getLogger(noisy).setLevel(logging.ERROR)

    db_path = Path(args.db)
    if not db_path.exists():
        sys.stderr.write(f"DB not found: {db_path}\n")
        return 2

    db = UnifiedDatabase(str(db_path))
    shutdown = GracefulShutdown()
    stats = Stats()

    try:
        row = db._conn.execute("SELECT status FROM bulk_scan_runs WHERE run_id = ?", (args.run_id,)).fetchone()
        if row is None:
            sys.stderr.write(f"run not found: {args.run_id!r}\n")
            return 4

        sys.stdout.write("loading language map + findings + liveness snapshots…\n")
        sys.stdout.flush()
        repo_languages = load_repo_languages(db, args.run_id)
        findings = load_findings_with_liveness(db, args.run_id)

        stats.total = len(findings)
        sys.stdout.write(
            f"run_id: {args.run_id}\n"
            f"pending findings: {stats.total:,}\n"
            f"repos w/ language data: {sum(1 for v in repo_languages.values() if v):,}/{len(repo_languages):,}\n"
            f"workers: {args.workers}\n"
            f"DB: {db_path}\n"
            f"status file: {STATUS_FILE}\n"
            f"PID: {os.getpid()}\n\n"
        )
        sys.stdout.flush()

        if not findings:
            sys.stdout.write("nothing pending — Stage 3 already complete for this run.\n")
            return 0

        if not args.quiet:
            t = threading.Thread(
                target=status_emitter,
                args=(stats, args.run_id, shutdown),
                daemon=True,
            )
            t.start()

        # Worker threads run compute_outcome (pure compute, no DB I/O).
        # Main thread consumes futures via as_completed and calls write_outcome
        # for each. This matches the pattern used in finish_stage2.py and
        # sidesteps sqlite3's default check_same_thread=True restriction.
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(compute_outcome, f, repo_languages): f for f in findings}
            for fut in as_completed(futures):
                if shutdown.requested:
                    for f2 in futures:
                        if not f2.done():
                            f2.cancel()
                    break
                finding = futures[fut]
                try:
                    state, candidates = fut.result()
                except Exception as e:
                    with stats.lock:
                        stats.errors += 1
                        stats.last_outcome = f"top-level: {type(e).__name__}"
                    continue
                # Main-thread DB write — sqlite connection used only from
                # the thread that created it (default check_same_thread=True
                # — the worker-thread write was the bug from the prior run).
                try:
                    write_outcome(db, args.run_id, finding, state, candidates, stats)
                except Exception as e:
                    with stats.lock:
                        stats.errors += 1
                        stats.last_outcome = f"write: {type(e).__name__}: {e}"

        sys.stdout.write("\n" + stats.render_line() + "\n")
        leftover_row = db._conn.execute(
            "SELECT COUNT(*) AS n FROM bulk_scan_findings "
            "WHERE run_id = ? AND method = 'pending' AND investigation_state = 'pending'",
            (args.run_id,),
        ).fetchone()
        leftover = int(leftover_row["n"])
        sys.stdout.write(
            f"\nfinished. skip_alive={stats.skipped_alive:,} skip_lang={stats.skipped_language:,} "
            f"no_cand={stats.investigated_no_cand:,} with_cand={stats.investigated_with_cand:,} "
            f"candidates_inserted={stats.candidates_inserted:,} errors={stats.errors:,} "
            f"still-pending={leftover:,} elapsed={stats.elapsed_s() / 60:.1f}min\n"
        )
        if stats.anomaly_flag():
            sys.stdout.write(
                f"\n!! anomaly flag was tripped — final no-cand rate "
                f"{100 * stats.no_cand_rate():.0f}%. Recheck whether GH API, "
                "Wikipedia, or local network was failing during the run.\n"
            )
        sys.stdout.flush()
        write_status_file(stats, args.run_id, final=True)
        return 0 if leftover == 0 else 1
    finally:
        try:
            db.close()
        except sqlite3.Error:
            pass


if __name__ == "__main__":
    sys.exit(main())
