"""Standalone Stage 2 completion: probe every unprobed URL in a bulk-scan run.

For ``bulk-20260514T042627Z`` the bulk of Stage 2 was completed during the
16-hour cache populate on 2026-05-22. Only a few thousand URLs remain
unprobed (those not yet in ``url_check_cache``, plus any new URLs that
``finish_stage1.py`` adds as it finishes the last 661 repos).

This script:

* Snapshots the set of URLs in the run's findings that are NOT yet in
  ``url_check_cache`` (or whose cache entries have expired).
* Runs them through ``bulk_scan.liveness.check_urls_bulk`` (the same
  HEAD-with-GET-fallback + stealth-fallback machinery used by N1 and the
  in-process bulk-scan runner — keeps semantics consistent with #190/#193/#198).
* Persists each result to ``url_check_cache`` via the ``on_result`` callback
  so a crash mid-batch loses at most the URLs currently in flight.

Concurrency: SAFE to run while ``finish_stage1.py`` and/or
``detect_languages.py`` are running. Does NOT take the bulk-scan lock. Writes
only to ``url_check_cache``; reads ``bulk_scan_findings`` (which Stage 1
appends to). The snapshot-at-start pattern means newly-added findings won't
be picked up by this invocation; re-fire when Stage 1 finishes to mop up.

Rate limiting: Stage 2 hits arbitrary destination hosts (not a single API).
Per-host 429s and timeouts are handled inside ``network.check_url`` and
recorded as status codes in the cache — they are valid responses, not
failures. We do NOT escalate-backoff on 429s here because that would
penalize all probes for one host's throttling.

What we DO watch for: sustained LOCAL failures (DNS broken, Wi-Fi off,
TCP-reset wave). When the recent error rate exceeds 50% over the last
~200 probes, the program pauses ``2 -> 5 -> 10 -> 20 -> 40 -> 80`` minutes
(escalating, never decays — see #249) so it doesn't churn an entire night
of dead probes if the laptop drops off the network. The pause counter
never resets — same pattern as the other stage finishers.

Observability: status line every 60s with overall progress, current rate,
ETA, and HTTP-status-family breakdown. Mirror to
``data/finish-stage2-status.txt``.

Usage::

    poetry run python tools/finish_stage2.py
    poetry run python tools/finish_stage2.py --run-id <other-run>
    poetry run python tools/finish_stage2.py --workers 30
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
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

# #265 — eager-import the chatty modules so each module's setup_logging()
# call fires BEFORE main()'s setLevel(ERROR) loop. Without these, the
# silencing runs on loggers with no handlers, then setup_logging fires
# during lazy import and resets level=INFO + adds a StreamHandler, defeating
# the silencing.
from gh_link_auditor import (  # noqa: E402
    archive_client,  # noqa: F401
    github_resolver,  # noqa: F401
    link_detective,  # noqa: F401
    policy_checker,  # noqa: F401
    redirect_resolver,  # noqa: F401
)
from gh_link_auditor.bulk_scan import liveness  # noqa: E402
from gh_link_auditor.bulk_scan.config import (  # noqa: E402
    LIVENESS_CACHE_TTL_HOURS,
    LIVENESS_WORKER_COUNT,
)
from gh_link_auditor.unified_db import UnifiedDatabase  # noqa: E402

DEFAULT_RUN_ID = "bulk-20260514T042627Z"
STATUS_FILE = _PROJECT_ROOT / "data" / "finish-stage2-status.txt"
LOG_INTERVAL_S = 60
BATCH_SIZE = 500  # urls per batch; status + program-level checks fire between batches
# Outer backoff (minutes) on local-network failures.
PROGRAM_BACKOFF_MINUTES = [2, 5, 10, 20, 40, 80]
# Window of recent probe outcomes used to detect "the network died" vs
# "one host is throttling." 200 probes is enough to dampen single-host noise.
ERROR_RATE_WINDOW = 200
ERROR_RATE_THRESHOLD = 0.50  # >50% local errors over the window -> pause


# ---------------------------------------------------------------------------


@dataclass
class Stats:
    started_monotonic: float = field(default_factory=time.monotonic)
    total: int = 0
    done: int = 0
    by_family: dict[str, int] = field(default_factory=dict)  # '2xx', '3xx', '4xx', '5xx', 'none', 'error'
    recent_outcomes: deque = field(default_factory=lambda: deque(maxlen=ERROR_RATE_WINDOW))
    top_error_hosts: dict[str, int] = field(default_factory=dict)
    program_backoff_count: int = 0
    last_url: str = ""
    last_outcome: str = ""
    last_pause_msg: str = ""

    def record(self, url: str, result: dict) -> None:
        self.done += 1
        self.last_url = url
        code = result.get("status_code")
        status = result.get("status", "")
        if code is None:
            family = "none" if status not in ("error",) else "error"
        elif 200 <= code < 300:
            family = "2xx"
        elif 300 <= code < 400:
            family = "3xx"
        elif 400 <= code < 500:
            family = "4xx"
        elif 500 <= code < 600:
            family = "5xx"
        else:
            family = "other"
        self.by_family[family] = self.by_family.get(family, 0) + 1
        # 'error' means we couldn't even get a status code — DNS, TCP, etc.
        # Those are the local-network failures we watch.
        is_local_error = (family == "error") or (family == "none" and status == "error")
        self.recent_outcomes.append(is_local_error)
        if is_local_error:
            from urllib.parse import urlparse

            try:
                host = urlparse(url).netloc or "?"
            except Exception:
                host = "?"
            self.top_error_hosts[host] = self.top_error_hosts.get(host, 0) + 1
        self.last_outcome = f"{family}({code})" if code is not None else family

    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_monotonic

    def per_min(self) -> float:
        e = self.elapsed_s()
        if e <= 0 or self.done == 0:
            return 0.0
        return self.done / (e / 60.0)

    def remaining(self) -> int:
        return max(0, self.total - self.done)

    def eta_str(self) -> str:
        rate = self.per_min()
        if rate <= 0:
            return "?"
        m = self.remaining() / rate
        return f"{m:.0f}m" if m < 60 else f"{m / 60:.1f}h"

    def family_str(self) -> str:
        order = ("2xx", "3xx", "4xx", "5xx", "none", "error", "other")
        parts = [f"{k}={self.by_family.get(k, 0):,}" for k in order if self.by_family.get(k)]
        return " ".join(parts) if parts else "-"

    def top_error_hosts_str(self, n: int = 3) -> str:
        items = sorted(self.top_error_hosts.items(), key=lambda kv: kv[1], reverse=True)[:n]
        return " ".join(f"{h}={c}" for h, c in items) if items else "-"

    def recent_error_rate(self) -> float:
        if not self.recent_outcomes:
            return 0.0
        return sum(self.recent_outcomes) / len(self.recent_outcomes)

    def render_line(self) -> str:
        now = datetime.now().strftime("%H:%M:%S")
        pct = (100.0 * self.done / self.total) if self.total else 0.0
        bo = f" pauses={self.program_backoff_count}" if self.program_backoff_count else ""
        return (
            f"[{now}] stage2 {self.done:,}/{self.total:,} ({pct:.1f}%) "
            f"{self.family_str()} rate={self.per_min():.0f}/min ETA={self.eta_str()}{bo} "
            f"err_rate={100 * self.recent_error_rate():.0f}%"
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
        sys.stdout.write(f"\n[!] shutdown signal {signum} — finishing in-flight probes and exiting\n")
        sys.stdout.flush()


def write_status_file(stats: Stats, run_id: str, *, final: bool = False) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    body = [
        f"run_id: {run_id}",
        f"status: {'finished' if final else 'running'}",
        f"started: {datetime.fromtimestamp(time.time() - stats.elapsed_s(), tz=timezone.utc).isoformat()}",
        f"now: {datetime.now(timezone.utc).isoformat()}",
        f"elapsed_min: {stats.elapsed_s() / 60:.1f}",
        f"total_urls: {stats.total}",
        f"probed: {stats.done}",
        f"remaining: {stats.remaining()}",
        f"rate_per_min: {stats.per_min():.1f}",
        f"eta: {stats.eta_str()}",
        f"families: {stats.family_str()}",
        f"recent_local_error_rate: {100 * stats.recent_error_rate():.1f}%",
        f"top_error_hosts: {stats.top_error_hosts_str(8)}",
        f"program_pauses_so_far: {stats.program_backoff_count}",
        f"last_url: {stats.last_url}",
        f"last_outcome: {stats.last_outcome}",
        f"last_pause_msg: {stats.last_pause_msg}",
    ]
    STATUS_FILE.write_text("\n".join(body) + "\n", encoding="utf-8")


def status_emitter(stats: Stats, run_id: str, shutdown: GracefulShutdown) -> None:
    last = 0.0
    while not shutdown.requested:
        now = time.monotonic()
        if now - last >= LOG_INTERVAL_S:
            sys.stdout.write(stats.render_line() + "\n")
            sys.stdout.flush()
            write_status_file(stats, run_id)
            last = now
        time.sleep(1)


# ---------------------------------------------------------------------------


def fetch_urls_needing_probe(db: UnifiedDatabase, run_id: str) -> list[str]:
    """Distinct dead_urls in the run that aren't in url_check_cache (or have expired).

    Reads bulk_scan_findings (placeholder rows from Stage 1, plus any earlier
    runs' findings — we filter to this run for correctness). Uses a single
    LEFT JOIN so we walk findings once rather than per-URL.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    rows = db._conn.execute(
        """
        SELECT DISTINCT bsf.dead_url AS url
        FROM bulk_scan_findings bsf
        LEFT JOIN url_check_cache ucc ON ucc.url = bsf.dead_url
        WHERE bsf.run_id = ?
          AND bsf.method = 'pending'
          AND (ucc.url IS NULL OR ucc.expires_at <= ?)
        """,
        (run_id, now_iso),
    ).fetchall()
    return [r["url"] for r in rows]


def program_backoff(stats: Stats, shutdown: GracefulShutdown, run_id: str) -> None:
    idx = min(stats.program_backoff_count, len(PROGRAM_BACKOFF_MINUTES) - 1)
    minutes = PROGRAM_BACKOFF_MINUTES[idx]
    stats.program_backoff_count += 1
    msg = (
        f"[!] local-network errors at {100 * stats.recent_error_rate():.0f}% over last "
        f"{len(stats.recent_outcomes)} probes — pausing program for {minutes} minutes "
        f"(escalation #{stats.program_backoff_count}). Top hosts: "
        f"{stats.top_error_hosts_str(5)}"
    )
    stats.last_pause_msg = msg
    sys.stdout.write("\n" + msg + "\n")
    sys.stdout.flush()
    write_status_file(stats, run_id)
    for _ in range(minutes * 60 // 5):
        if shutdown.requested:
            return
        time.sleep(5)


# ---------------------------------------------------------------------------


def probe_batch(
    db: UnifiedDatabase,
    urls: list[str],
    workers: int,
    stats: Stats,
    db_lock: threading.Lock,
) -> None:
    """Probe one batch of URLs and persist results as they come in.

    Uses a private ThreadPoolExecutor (rather than calling
    ``liveness.check_urls_bulk`` directly) so we can persist results from the
    main thread and update stats with proper locking — the existing helper
    invokes ``on_result`` on the main thread already, but we want fine-grained
    control over the cache write + the recent-outcomes deque.
    """
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(liveness._probe_one, u): u for u in urls}
        for fut in as_completed(futures):
            url, result = fut.result()
            # Write cache + record stats from the main loop (sqlite-safe).
            with db_lock:
                try:
                    db.cache_url_check(
                        url,
                        http_status=result.get("status_code"),
                        final_url=result.get("final_url"),
                        is_bot_blocked=bool(result.get("is_bot_blocked")),
                        ttl_hours=LIVENESS_CACHE_TTL_HOURS,
                    )
                except sqlite3.Error as e:
                    logging.getLogger(__name__).warning("cache write failed for %s: %s", url, e)
            stats.record(url, result)


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resume Stage 2 (URL liveness probes) for a bulk-scan run.")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument(
        "--db",
        default=str(Path.home() / ".ghla" / "ghla.db"),
        help="path to ghla.db (default: ~/.ghla/ghla.db)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=LIVENESS_WORKER_COUNT,
        help=f"parallel probe workers (default: {LIVENESS_WORKER_COUNT})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"URLs per batch between status/backoff checks (default: {BATCH_SIZE})",
    )
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
    # Silence verbose modules — same set as finish_stage3.py per #256.
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
    db_lock = threading.Lock()

    try:
        row = db._conn.execute("SELECT status FROM bulk_scan_runs WHERE run_id = ?", (args.run_id,)).fetchone()
        if row is None:
            sys.stderr.write(f"run not found: {args.run_id!r}\n")
            return 4

        urls = fetch_urls_needing_probe(db, args.run_id)
        stats.total = len(urls)
        sys.stdout.write(
            f"run_id: {args.run_id}\n"
            f"urls needing probe: {stats.total:,}\n"
            f"workers: {args.workers}\n"
            f"batch size: {args.batch_size}\n"
            f"cache TTL: {LIVENESS_CACHE_TTL_HOURS}h\n"
            f"DB: {db_path}\n"
            f"status file: {STATUS_FILE}\n"
            f"PID: {os.getpid()}\n\n"
        )
        sys.stdout.flush()

        if not urls:
            sys.stdout.write(
                "nothing to probe — every URL in this run's findings is already in url_check_cache (within TTL).\n"
            )
            return 0

        if not args.quiet:
            t = threading.Thread(
                target=status_emitter,
                args=(stats, args.run_id, shutdown),
                daemon=True,
            )
            t.start()

        # Walk in batches so the status + backoff checks fire between batches.
        i = 0
        while i < len(urls) and not shutdown.requested:
            batch = urls[i : i + args.batch_size]
            probe_batch(db, batch, args.workers, stats, db_lock)
            i += len(batch)

            # After each batch: if local-network errors dominate, pause.
            # (Per-host 429s don't count as local errors — those are valid
            #  status codes and live in the 4xx family.)
            if len(stats.recent_outcomes) >= ERROR_RATE_WINDOW and stats.recent_error_rate() >= ERROR_RATE_THRESHOLD:
                program_backoff(stats, shutdown, args.run_id)
                # Clear the window so we don't immediately re-trigger on the
                # same evidence after a pause.
                stats.recent_outcomes.clear()

        # Final summary.
        sys.stdout.write("\n" + stats.render_line() + "\n")
        # Re-snapshot to see if Stage 1 added more URLs while we worked.
        leftover = len(fetch_urls_needing_probe(db, args.run_id))
        sys.stdout.write(
            f"\nfinished. probed={stats.done:,} pauses={stats.program_backoff_count} "
            f"still-needing-probe={leftover} elapsed={stats.elapsed_s() / 60:.1f}min\n"
        )
        sys.stdout.write(f"\nfamily breakdown: {stats.family_str()}\n")
        if stats.top_error_hosts:
            sys.stdout.write(f"top local-error hosts: {stats.top_error_hosts_str(10)}\n")
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
