"""Backfill ``detected_language`` for every inventoried repo in a bulk-scan run.

Why: Stage 3's English-only filter (#238) reads ``bulk_scan_repos.detected_language``
and skips findings from non-English repos. For the long-stalled ``T042627Z``
run, this column is NULL for all 7,500 repos, so the filter never fires and
non-English-doc URLs get investigated needlessly. This program walks the
inventoried repos, fetches each one's README from raw.githubusercontent.com,
runs ``langdetect`` on the first ~5,000 chars, and writes the ISO code into
``bulk_scan_repos.detected_language``.

Concurrency: SAFE to run while ``finish_stage1.py`` is also running on the
same run. We do NOT take the per-(run_id, host) bulk-scan lock — Stage 1
writes the ``status``/``doc_files_json`` columns, this script writes only the
``detected_language`` column. SQLite serializes writers automatically.

Rate limiting: raw.githubusercontent.com is a Fastly CDN that returns 429
under sustained bursts (~300/sec aggregate). Two layers of backoff:

  * Inner (per-request): on 429, sleep for ``Retry-After`` if present, else
    ``2s -> 4 -> 8 -> 16 -> 32 -> 64 -> 128 -> 256 -> 512 -> 900s`` (capped).
    Max 10 retries per README variant fetch.

  * Outer (per-program): if inner retries exhaust on the same repo, the
    whole program pauses ``2 -> 5 -> 10 -> 20 -> 40 -> 80`` minutes,
    escalating each storm. The counter never decrements -- a night of
    repeated storms gets progressively longer waits. The repo stays
    unclassified for now and gets retried at the end of the pass.

Observability: status line every 60s + mirror to ``data/detect-languages-status.txt``.

Usage::

    poetry run python tools/detect_languages.py
    poetry run python tools/detect_languages.py --run-id <other-run>

Safe to re-run. Only walks repos with ``detected_language IS NULL`` and
``status = 'inventoried'``. Idempotent.
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
from langdetect import DetectorFactory, LangDetectException, detect

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
from gh_link_auditor.unified_db import UnifiedDatabase  # noqa: E402

DetectorFactory.seed = 0  # deterministic detection

DEFAULT_RUN_ID = "bulk-20260514T042627Z"
STATUS_FILE = _PROJECT_ROOT / "data" / "detect-languages-status.txt"
LOG_INTERVAL_S = 60
RAW_BASE = "https://raw.githubusercontent.com"
README_VARIANTS = ("README.md", "README.rst", "README.txt", "README")
MIN_TEXT_LEN = 100  # langdetect is unreliable below this
MAX_TEXT_LEN = 5000  # cap to keep detection fast
# Outer backoff (minutes) on sustained rate limiting from the raw CDN.
PROGRAM_BACKOFF_MINUTES = [2, 5, 10, 20, 40, 80]
PER_REQUEST_BASE_S = 2.0
PER_REQUEST_MAX_S = 900.0  # 15 min cap on single retry
PER_REQUEST_MAX_RETRIES = 10
# Gentle inter-request floor so we don't hammer the CDN ourselves.
INTER_REQUEST_DELAY_S = 0.2


# ---------------------------------------------------------------------------


class RateLimitExhausted(RuntimeError):
    """Raised when raw-CDN 429s persist past PER_REQUEST_MAX_RETRIES."""


@dataclass
class Stats:
    started_monotonic: float = field(default_factory=time.monotonic)
    total: int = 0
    processed_ok: int = 0
    processed_unknown: int = 0  # README missing / too short / can't classify
    processed_error: int = 0
    by_lang: dict[str, int] = field(default_factory=dict)
    program_backoff_count: int = 0
    last_repo: str = ""
    last_lang: str = ""
    last_429_msg: str = ""

    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_monotonic

    def processed(self) -> int:
        return self.processed_ok + self.processed_unknown + self.processed_error

    def remaining(self) -> int:
        return max(0, self.total - self.processed())

    def per_min(self) -> float:
        e = self.elapsed_s()
        if e <= 0 or self.processed() == 0:
            return 0.0
        return self.processed() / (e / 60.0)

    def eta_str(self) -> str:
        rate = self.per_min()
        if rate <= 0:
            return "?"
        m = self.remaining() / rate
        return f"{m:.0f}m" if m < 60 else f"{m / 60:.1f}h"

    def top_langs(self, n: int = 6) -> str:
        items = sorted(self.by_lang.items(), key=lambda kv: kv[1], reverse=True)[:n]
        return " ".join(f"{k}={v}" for k, v in items) if items else "-"

    def render_line(self) -> str:
        now = datetime.now().strftime("%H:%M:%S")
        pct = (100.0 * self.processed() / self.total) if self.total else 0.0
        bo = f" backoffs={self.program_backoff_count}" if self.program_backoff_count else ""
        last = f" last={self.last_repo}->{self.last_lang}" if self.last_repo else ""
        return (
            f"[{now}] lang {self.processed():,}/{self.total:,} "
            f"({pct:.1f}%) ok={self.processed_ok:,} unk={self.processed_unknown:,} "
            f"err={self.processed_error:,} rate={self.per_min():.1f}/min "
            f"ETA={self.eta_str()} top: {self.top_langs()}{bo}{last}"
        )


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
        sys.stdout.write(f"\n[!] shutdown signal {signum} — finishing current repo and exiting\n")
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
        f"total: {stats.total}",
        f"processed: {stats.processed()}",
        f"processed_ok: {stats.processed_ok}",
        f"processed_unknown: {stats.processed_unknown}",
        f"processed_error: {stats.processed_error}",
        f"remaining: {stats.remaining()}",
        f"rate_per_min: {stats.per_min():.2f}",
        f"eta: {stats.eta_str()}",
        f"top_langs: {stats.top_langs(10)}",
        f"program_backoffs_so_far: {stats.program_backoff_count}",
        f"last_repo: {stats.last_repo}",
        f"last_lang: {stats.last_lang}",
        f"last_rate_limit_msg: {stats.last_429_msg}",
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


def fetch_readme_text(
    client: httpx.Client,
    repo: str,
    variant: str,
) -> str | None:
    """One-variant fetch with retry-on-429. Raises RateLimitExhausted past max retries.

    Returns the text on 200, ``None`` on 404 / other non-rate-limit failures.
    """
    url = f"{RAW_BASE}/{repo}/HEAD/{variant}"
    backoff = PER_REQUEST_BASE_S
    last_msg = ""
    for _attempt in range(PER_REQUEST_MAX_RETRIES):
        time.sleep(INTER_REQUEST_DELAY_S)
        try:
            r = client.get(url, follow_redirects=True, timeout=15)
        except (httpx.HTTPError, OSError) as e:
            last_msg = f"{type(e).__name__}: {e}"
            time.sleep(min(backoff, PER_REQUEST_MAX_S))
            backoff = min(backoff * 2, PER_REQUEST_MAX_S)
            continue
        if r.status_code == 200:
            return r.text
        if r.status_code == 404:
            return None
        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            wait_s = backoff
            if retry_after:
                try:
                    wait_s = float(retry_after)
                except ValueError:
                    pass
            wait_s = min(wait_s, PER_REQUEST_MAX_S)
            last_msg = f"429 on {variant}, sleeping {wait_s:.0f}s"
            time.sleep(wait_s)
            backoff = min(backoff * 2, PER_REQUEST_MAX_S)
            continue
        # Other non-2xx, non-404, non-429 — treat as soft fail, move on.
        last_msg = f"status={r.status_code} on {variant}"
        return None
    # Out of retries on 429s
    raise RateLimitExhausted(f"{repo} {variant}: {last_msg}")


def detect_repo_language(client: httpx.Client, repo: str) -> str | None:
    """Try each README variant; return ISO code or None.

    Raises RateLimitExhausted upward so the main loop can program-backoff.
    """
    for variant in README_VARIANTS:
        text = fetch_readme_text(client, repo, variant)
        if text is None or len(text) < MIN_TEXT_LEN:
            continue
        try:
            return detect(text[:MAX_TEXT_LEN])
        except LangDetectException:
            continue
    return None


# ---------------------------------------------------------------------------


def fetch_pending_repos(db: UnifiedDatabase, run_id: str) -> list[str]:
    """Inventoried repos still missing a detected_language."""
    rows = db._conn.execute(
        "SELECT repo_full_name FROM bulk_scan_repos "
        "WHERE run_id = ? AND status = 'inventoried' "
        "AND detected_language IS NULL "
        "ORDER BY repo_full_name",
        (run_id,),
    ).fetchall()
    return [r["repo_full_name"] for r in rows]


def write_lang(db: UnifiedDatabase, run_id: str, repo: str, lang: str | None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    # Use COALESCE so concurrent writers don't clobber if another agent set it first.
    with db._conn:
        db._conn.execute(
            "UPDATE bulk_scan_repos SET detected_language = COALESCE(detected_language, ?), "
            "updated_at = ? "
            "WHERE run_id = ? AND repo_full_name = ?",
            (lang, now, run_id, repo),
        )


def program_backoff(stats: Stats, shutdown: GracefulShutdown, run_id: str) -> None:
    idx = min(stats.program_backoff_count, len(PROGRAM_BACKOFF_MINUTES) - 1)
    minutes = PROGRAM_BACKOFF_MINUTES[idx]
    stats.program_backoff_count += 1
    msg = (
        f"[!] raw-CDN sustained rate limit — pausing program for {minutes} minutes "
        f"(escalation #{stats.program_backoff_count})"
    )
    stats.last_429_msg = msg
    sys.stdout.write("\n" + msg + "\n")
    sys.stdout.flush()
    write_status_file(stats, run_id)
    for _ in range(minutes * 60 // 5):
        if shutdown.requested:
            return
        time.sleep(5)


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill detected_language for inventoried repos.")
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
        "langdetect",
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
        # Quick run existence check
        row = db._conn.execute("SELECT status FROM bulk_scan_runs WHERE run_id = ?", (args.run_id,)).fetchone()
        if row is None:
            sys.stderr.write(f"run not found: {args.run_id!r}\n")
            return 4

        repos = fetch_pending_repos(db, args.run_id)
        stats.total = len(repos)
        sys.stdout.write(
            f"run_id: {args.run_id}\n"
            f"repos needing detected_language: {stats.total}\n"
            f"DB: {db_path}\n"
            f"status file: {STATUS_FILE}\n"
            f"PID: {os.getpid()}\n\n"
        )
        sys.stdout.flush()

        if not repos:
            sys.stdout.write("nothing to do — every inventoried repo already has detected_language.\n")
            return 0

        client = httpx.Client(
            headers={"User-Agent": "gh-link-auditor-langdetect"},
            timeout=15.0,
            follow_redirects=True,
        )

        if not args.quiet:
            t = threading.Thread(
                target=status_emitter,
                args=(stats, args.run_id, shutdown),
                daemon=True,
            )
            t.start()

        deferred: list[str] = []  # repos that hit rate-limit storms; retried later

        try:
            for repo in repos:
                if shutdown.requested:
                    break
                stats.last_repo = repo
                try:
                    lang = detect_repo_language(client, repo)
                except RateLimitExhausted as e:
                    stats.last_429_msg = str(e)
                    program_backoff(stats, shutdown, args.run_id)
                    if shutdown.requested:
                        break
                    deferred.append(repo)
                    continue
                except Exception as e:
                    write_lang(db, args.run_id, repo, None)
                    stats.processed_error += 1
                    stats.last_lang = f"err:{type(e).__name__}"
                    continue

                if lang is None:
                    # No README we could classify — record explicit 'unknown' so
                    # we don't keep retrying. Stage 3 treats NULL as include;
                    # use literal 'unknown' for that signal and let operator
                    # decide later. Until then: NULL is fine too.
                    write_lang(db, args.run_id, repo, "unknown")
                    stats.processed_unknown += 1
                    stats.last_lang = "unknown"
                else:
                    write_lang(db, args.run_id, repo, lang)
                    stats.by_lang[lang] = stats.by_lang.get(lang, 0) + 1
                    stats.processed_ok += 1
                    stats.last_lang = lang

            # Pass 2: anything deferred due to rate-limit storms gets one more try.
            if deferred and not shutdown.requested:
                sys.stdout.write(
                    f"\n[pass 2] retrying {len(deferred)} repos that were skipped during rate-limit storms\n"
                )
                sys.stdout.flush()
                for repo in deferred:
                    if shutdown.requested:
                        break
                    stats.last_repo = repo
                    try:
                        lang = detect_repo_language(client, repo)
                    except RateLimitExhausted as e:
                        stats.last_429_msg = str(e)
                        program_backoff(stats, shutdown, args.run_id)
                        continue
                    except Exception as e:
                        write_lang(db, args.run_id, repo, None)
                        stats.processed_error += 1
                        stats.last_lang = f"err:{type(e).__name__}"
                        continue
                    if lang is None:
                        write_lang(db, args.run_id, repo, "unknown")
                        stats.processed_unknown += 1
                        stats.last_lang = "unknown"
                    else:
                        write_lang(db, args.run_id, repo, lang)
                        stats.by_lang[lang] = stats.by_lang.get(lang, 0) + 1
                        stats.processed_ok += 1
                        stats.last_lang = lang
        finally:
            client.close()

        # Final summary
        final_remaining = len(fetch_pending_repos(db, args.run_id))
        sys.stdout.write("\n" + stats.render_line() + "\n")
        sys.stdout.write(
            f"\nfinished. ok={stats.processed_ok:,} unknown={stats.processed_unknown:,} "
            f"err={stats.processed_error:,} still-needing-detection={final_remaining} "
            f"backoffs={stats.program_backoff_count} "
            f"elapsed={stats.elapsed_s() / 60:.1f}min\n"
        )
        sys.stdout.write(f"\nlanguage breakdown: {stats.top_langs(20)}\n")
        sys.stdout.flush()
        write_status_file(stats, args.run_id, final=True)
        return 0
    finally:
        try:
            db.close()
        except sqlite3.Error:
            pass


if __name__ == "__main__":
    sys.exit(main())
