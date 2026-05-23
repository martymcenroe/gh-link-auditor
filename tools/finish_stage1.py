"""Standalone Stage 1 completion for bulk-20260514T042627Z.

Resumes Stage 1 (inventory) for the 661 still-pending repos in the 440k-finding
run that was abandoned on 2026-05-14. Designed to be launched and walked away
from. Built-in observability + sane failure handling so you don't have to babysit.

Design rules (lessons from prior disasters):

* **No quality stop-loss.** The run completes or you stop it. Period.
* **No in-memory accumulation across the whole run.** Each repo's results are
  written to the DB as soon as they're produced; a crash loses at most the
  one repo currently in flight.
* **No overwriting of prior work.** Repos already in `'inventoried'` status
  are skipped entirely. The DELETE-then-INSERT anti-pattern is gone.
* **Failures don't clutch forward.** Per-repo errors are recorded and the
  next repo is tried; sustained rate-limiting pauses the whole program with
  exponential backoff (5min -> 10 -> 20 -> 40 -> 80 -> 120, then capped) so
  the program doesn't pound through every remaining repo as an error.
* **Observability over silence.** Status line every 60s with progress, rate,
  ETA, and the most recent repo touched. Mirrored to a status file you can
  ``Get-Content`` from another window.
* **Multi-agent safe.** Acquires the bulk_scan_locks row before doing any
  work; a second invocation while one is running exits with a clear message.

Usage:

    poetry run python tools/finish_stage1.py

To force a different run id:

    poetry run python tools/finish_stage1.py --run-id bulk-XXXXX
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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Ensure src/ is importable when the tool is run from project root.
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
from gh_link_auditor.bulk_scan import inventory, process_lock, storage  # noqa: E402
from gh_link_auditor.bulk_scan.gh_client import GitHubRateLimitedClient  # noqa: E402
from gh_link_auditor.unified_db import UnifiedDatabase  # noqa: E402

DEFAULT_RUN_ID = "bulk-20260514T042627Z"
STATUS_FILE = _PROJECT_ROOT / "data" / "finish-stage1-status.txt"
LOG_INTERVAL_S = 60
# Adaptive program-level backoff schedule (minutes) — kicks in only after
# the GitHub client's internal retries have already been exhausted on the
# same repo. We pause the whole program rather than burn through repos as
# errors.
PROGRAM_BACKOFF_MINUTES = [5, 10, 20, 40, 80, 120]


# ---------------------------------------------------------------------------


@dataclass
class Stats:
    started_monotonic: float = field(default_factory=time.monotonic)
    total_repos: int = 0
    done_at_start: int = 0  # repos already inventoried before this run started
    processed_ok: int = 0
    processed_error: int = 0
    findings_added: int = 0
    last_repo: str = ""
    last_repo_outcome: str = ""
    program_backoff_count: int = 0  # how many times we've had to pause the whole program
    last_429_msg: str = ""

    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_monotonic

    def processed(self) -> int:
        return self.processed_ok + self.processed_error

    def remaining(self) -> int:
        return self.total_repos - self.processed()

    def repos_per_min(self) -> float:
        e = self.elapsed_s()
        if e <= 0 or self.processed() == 0:
            return 0.0
        return self.processed() / (e / 60.0)

    def eta_str(self) -> str:
        rate = self.repos_per_min()
        if rate <= 0:
            return "?"
        remaining_min = self.remaining() / rate
        if remaining_min < 60:
            return f"{remaining_min:.0f}m"
        return f"{remaining_min / 60:.1f}h"

    def render_line(self) -> str:
        now = datetime.now().strftime("%H:%M:%S")
        pct = (100.0 * self.processed() / self.total_repos) if self.total_repos else 0.0
        bo = f" backoffs={self.program_backoff_count}" if self.program_backoff_count else ""
        last = f" last={self.last_repo}" if self.last_repo else ""
        return (
            f"[{now}] stage1 {self.processed():,}/{self.total_repos:,} "
            f"({pct:.1f}%) ok={self.processed_ok:,} err={self.processed_error:,} "
            f"findings+={self.findings_added:,} rate={self.repos_per_min():.1f}/min "
            f"ETA={self.eta_str()}{bo}{last}"
        )


# ---------------------------------------------------------------------------


class GracefulShutdown:
    """Capture SIGINT/SIGTERM and let the inner loop notice."""

    def __init__(self) -> None:
        self.requested = False
        signal.signal(signal.SIGINT, self._handler)
        try:
            signal.signal(signal.SIGTERM, self._handler)
        except (AttributeError, ValueError):
            # SIGTERM not available on Windows-Python in some shells.
            pass

    def _handler(self, signum: int, frame: object) -> None:  # noqa: ARG002
        self.requested = True
        sys.stdout.write(f"\n[!] shutdown signal {signum} — finishing current repo then exiting cleanly\n")
        sys.stdout.flush()


# ---------------------------------------------------------------------------


def write_status_file(stats: Stats, run_id: str, *, final: bool = False) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    body = [
        f"run_id: {run_id}",
        f"status: {'finished' if final else 'running'}",
        f"started: {datetime.fromtimestamp(time.time() - stats.elapsed_s(), tz=timezone.utc).isoformat()}",
        f"now: {datetime.now(timezone.utc).isoformat()}",
        f"elapsed_min: {stats.elapsed_s() / 60:.1f}",
        f"total_repos: {stats.total_repos}",
        f"done_before_run: {stats.done_at_start}",
        f"processed: {stats.processed()}",
        f"processed_ok: {stats.processed_ok}",
        f"processed_error: {stats.processed_error}",
        f"remaining: {stats.remaining()}",
        f"findings_added: {stats.findings_added}",
        f"rate_per_min: {stats.repos_per_min():.2f}",
        f"eta: {stats.eta_str()}",
        f"program_backoffs_so_far: {stats.program_backoff_count}",
        f"last_repo: {stats.last_repo}",
        f"last_repo_outcome: {stats.last_repo_outcome}",
        f"last_rate_limit_msg: {stats.last_429_msg}",
    ]
    STATUS_FILE.write_text("\n".join(body) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------


def fetch_pending_repos(db: UnifiedDatabase, run_id: str) -> list[str]:
    rows = db._conn.execute(
        "SELECT repo_full_name FROM bulk_scan_repos WHERE run_id = ? AND status = 'pending' ORDER BY repo_full_name",
        (run_id,),
    ).fetchall()
    return [r["repo_full_name"] for r in rows]


def repo_status(db: UnifiedDatabase, run_id: str, repo: str) -> str | None:
    row = db._conn.execute(
        "SELECT status FROM bulk_scan_repos WHERE run_id = ? AND repo_full_name = ?",
        (run_id, repo),
    ).fetchone()
    return row["status"] if row else None


def total_repo_count(db: UnifiedDatabase, run_id: str) -> int:
    row = db._conn.execute("SELECT COUNT(*) AS n FROM bulk_scan_repos WHERE run_id = ?", (run_id,)).fetchone()
    return int(row["n"])


def already_inventoried_count(db: UnifiedDatabase, run_id: str) -> int:
    row = db._conn.execute(
        "SELECT COUNT(*) AS n FROM bulk_scan_repos WHERE run_id = ? AND status = 'inventoried'",
        (run_id,),
    ).fetchone()
    return int(row["n"])


# ---------------------------------------------------------------------------


def write_repo_atomically(
    db: UnifiedDatabase,
    run_id: str,
    repo: str,
    result: dict,
) -> int:
    """One transaction: mark repo inventoried + insert all its findings.

    Returns count of finding rows inserted. If any step fails the whole
    transaction rolls back; the repo stays 'pending' and will be retried
    on the next pass.
    """
    docs = result["doc_files"]
    urls = result["urls"]
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    with db._conn:  # implicit BEGIN/COMMIT on success, ROLLBACK on exception
        db._conn.execute(
            "UPDATE bulk_scan_repos SET doc_files_json = ?, url_count = ?, "
            "status = 'inventoried', updated_at = ? "
            "WHERE run_id = ? AND repo_full_name = ?",
            (
                _json_dumps(docs),
                len(urls),
                now,
                run_id,
                repo,
            ),
        )
        for url, src, ln in urls:
            db._conn.execute(
                "INSERT INTO bulk_scan_findings "
                "(run_id, repo_full_name, source_file, line_number, dead_url, "
                " candidate_url, method, tier, similarity_score, verified_live, "
                " confidence, surfaced, created_at, investigation_state) "
                "VALUES (?, ?, ?, ?, ?, '', 'pending', 0, NULL, 0, 0.0, 0, ?, 'pending')",
                (run_id, repo, src, ln, url, now),
            )
            inserted += 1
    return inserted


def _json_dumps(obj: object) -> str:
    import json

    return json.dumps(obj)


def mark_error_safely(db: UnifiedDatabase, run_id: str, repo: str, error: str) -> None:
    """Record a non-rate-limit failure so we don't loop on it. Truncates long errors."""
    now = datetime.now(timezone.utc).isoformat()
    with db._conn:
        db._conn.execute(
            "UPDATE bulk_scan_repos SET status = 'error', error = ?, updated_at = ? "
            "WHERE run_id = ? AND repo_full_name = ?",
            (error[:500], now, run_id, repo),
        )


# ---------------------------------------------------------------------------


class RateLimitExhausted(Exception):
    """Raised when the GH client's internal retries are spent on the same repo."""


def is_rate_limited_response(e: Exception) -> bool:
    """True if exception traces back to a rate-limit / 403-secondary response."""
    if isinstance(e, RateLimitExhausted):
        return True
    if isinstance(e, httpx.HTTPStatusError):
        if e.response.status_code == 429:
            return True
        if e.response.status_code == 403:
            text = (e.response.text or "").lower()
            if "secondary rate limit" in text or "abuse" in text or "rate limit" in text:
                return True
    return False


def inventory_one_repo(
    repo: str,
    api: GitHubRateLimitedClient,
    raw: httpx.Client,
) -> dict:
    """Wrapper that turns an exhausted-retries rate-limit response into an exception.

    The client's ``.get`` returns the rate-limited response after max_retries.
    Calling ``raise_for_status`` then throws — we re-raise as RateLimitExhausted
    so the program-level backoff loop catches it.
    """
    try:
        return inventory.inventory_repo(repo, api, raw)
    except httpx.HTTPStatusError as e:
        if is_rate_limited_response(e):
            raise RateLimitExhausted(
                f"rate limited after client retries on {repo}: status={e.response.status_code}"
            ) from e
        raise


# ---------------------------------------------------------------------------


def program_backoff(stats: Stats, shutdown: GracefulShutdown, run_id: str) -> None:
    """Sleep the whole program with escalating duration on sustained rate-limiting."""
    idx = min(stats.program_backoff_count, len(PROGRAM_BACKOFF_MINUTES) - 1)
    minutes = PROGRAM_BACKOFF_MINUTES[idx]
    stats.program_backoff_count += 1
    msg = (
        f"[!] sustained rate limit — pausing program for {minutes} minutes (escalation #{stats.program_backoff_count})"
    )
    stats.last_429_msg = msg
    sys.stdout.write("\n" + msg + "\n")
    sys.stdout.flush()
    write_status_file(stats, run_id)
    # Sleep in 5-second chunks so Ctrl+C is responsive.
    for _ in range(minutes * 60 // 5):
        if shutdown.requested:
            return
        time.sleep(5)


# ---------------------------------------------------------------------------


def status_emitter(stats: Stats, run_id: str, shutdown: GracefulShutdown) -> None:
    """Background thread: print status line every LOG_INTERVAL_S, mirror to file."""
    last_emit = 0.0
    while not shutdown.requested:
        now = time.monotonic()
        if now - last_emit >= LOG_INTERVAL_S:
            sys.stdout.write(stats.render_line() + "\n")
            sys.stdout.flush()
            write_status_file(stats, run_id)
            last_emit = now
        time.sleep(1)


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resume Stage 1 inventory for a bulk-scan run.")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument(
        "--db",
        default=str(Path.home() / ".ghla" / "ghla.db"),
        help="path to ghla.db (default: ~/.ghla/ghla.db)",
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

    # Lock the run so a second agent can't race us.
    try:
        process_lock.acquire(db, args.run_id)
    except process_lock.LockBusyError as e:
        sys.stderr.write(f"{e}\n")
        return 3

    shutdown = GracefulShutdown()
    stats = Stats()
    stats.total_repos = total_repo_count(db, args.run_id)
    stats.done_at_start = already_inventoried_count(db, args.run_id)
    stats.processed_ok = 0  # this run's processed; counters are independent of done_at_start

    try:
        run = storage.get_run(db, args.run_id)
        if run is None:
            sys.stderr.write(f"run not found: {args.run_id!r}\n")
            return 4

        pending = fetch_pending_repos(db, args.run_id)
        sys.stdout.write(
            f"run_id: {args.run_id}\n"
            f"status: {run['status']}\n"
            f"total repos in run: {stats.total_repos}\n"
            f"already inventoried: {stats.done_at_start}\n"
            f"pending (to do now): {len(pending)}\n"
            f"DB: {db_path}\n"
            f"status file: {STATUS_FILE}\n"
            f"PID: {os.getpid()}\n\n"
        )
        sys.stdout.flush()

        if not pending:
            sys.stdout.write("nothing pending — Stage 1 already complete for this run.\n")
            return 0

        # The total to track is the pending count (so percentages line up with
        # this invocation's work). done_at_start is reported separately.
        stats.total_repos = len(pending)

        api = inventory.build_api_client()
        # Bump internal retries to ride out longer rate-limit storms before the
        # program-level escalation kicks in.
        if hasattr(api, "_max_retries"):
            api._max_retries = 15  # noqa: SLF001
            api._base_backoff = 4.0  # noqa: SLF001
        raw = inventory.build_raw_client()

        if not args.quiet:
            t = threading.Thread(
                target=status_emitter,
                args=(stats, args.run_id, shutdown),
                daemon=True,
            )
            t.start()

        try:
            for repo in pending:
                if shutdown.requested:
                    break
                # Re-check status — another agent may have claimed it in another DB.
                cur = repo_status(db, args.run_id, repo)
                if cur != "pending":
                    continue

                stats.last_repo = repo
                try:
                    result = inventory_one_repo(repo, api, raw)
                except RateLimitExhausted as e:
                    stats.last_repo_outcome = f"rate-limited: {e}"
                    stats.last_429_msg = str(e)
                    program_backoff(stats, shutdown, args.run_id)
                    if shutdown.requested:
                        break
                    # Retry the same repo on next iteration — leave it 'pending'.
                    # We re-add it to the front by NOT continuing past here; the
                    # outer 'for' will move on, but a periodic re-pull below
                    # picks up still-pending repos. To avoid skipping, we'll
                    # retry immediately by attempting it once more right now.
                    try:
                        result = inventory_one_repo(repo, api, raw)
                    except Exception:
                        # Still failing — leave it 'pending' and move on to other
                        # repos. We'll come back at the end.
                        continue
                except Exception as e:
                    mark_error_safely(db, args.run_id, repo, repr(e))
                    stats.processed_error += 1
                    stats.last_repo_outcome = f"error: {e!r}"
                    continue

                try:
                    inserted = write_repo_atomically(db, args.run_id, repo, result)
                except Exception as e:
                    # DB write failure is unusual; record but don't crash.
                    mark_error_safely(db, args.run_id, repo, f"db-write: {e!r}")
                    stats.processed_error += 1
                    stats.last_repo_outcome = f"db-error: {e!r}"
                    continue
                stats.processed_ok += 1
                stats.findings_added += inserted
                stats.last_repo_outcome = f"ok ({inserted} URLs)"

            # Pass 2: pick up any repos still 'pending' (skipped during rate-limit
            # storms above). This loop runs at most once and short-circuits if
            # nothing is left.
            still_pending = fetch_pending_repos(db, args.run_id)
            if still_pending and not shutdown.requested:
                sys.stdout.write(
                    f"\n[pass 2] retrying {len(still_pending)} repos that were skipped during rate-limit storms\n"
                )
                sys.stdout.flush()
                for repo in still_pending:
                    if shutdown.requested:
                        break
                    stats.last_repo = repo
                    try:
                        result = inventory_one_repo(repo, api, raw)
                    except RateLimitExhausted as e:
                        stats.last_429_msg = str(e)
                        program_backoff(stats, shutdown, args.run_id)
                        continue
                    except Exception as e:
                        mark_error_safely(db, args.run_id, repo, repr(e))
                        stats.processed_error += 1
                        continue
                    try:
                        inserted = write_repo_atomically(db, args.run_id, repo, result)
                    except Exception as e:
                        mark_error_safely(db, args.run_id, repo, f"db-write: {e!r}")
                        stats.processed_error += 1
                        continue
                    stats.processed_ok += 1
                    stats.findings_added += inserted
                    stats.last_repo_outcome = f"ok ({inserted} URLs)"
        finally:
            try:
                api.close()
            except Exception:
                pass
            raw.close()

        # Final summary.
        final_pending = len(fetch_pending_repos(db, args.run_id))
        sys.stdout.write("\n" + stats.render_line() + "\n")
        sys.stdout.write(
            f"\nfinished. ok={stats.processed_ok:,} error={stats.processed_error:,} "
            f"still-pending={final_pending} findings-added={stats.findings_added:,} "
            f"program-backoffs={stats.program_backoff_count} "
            f"elapsed={stats.elapsed_s() / 60:.1f}min\n"
        )
        sys.stdout.flush()
        write_status_file(stats, args.run_id, final=True)
        return 0 if final_pending == 0 else 1
    finally:
        try:
            process_lock.release(db, args.run_id)
        except sqlite3.Error:
            pass
        db.close()


if __name__ == "__main__":
    sys.exit(main())
