"""Tests for ``gh_link_auditor.bulk_scan.progress``.

The progress module is the single source of truth for bulk-scan status
lines, used by both ``runner.run_full()``'s in-process emitter and the
``tools/watch_bulk_scan.py`` out-of-process poller. The byte-format
matches the PR #271 schema and ``tools/finish_stage*.py``.

These tests pin the rendered format so the next refactor can't silently
change it. See #368.
"""

from __future__ import annotations

import re
import time
from collections import deque

from gh_link_auditor.bulk_scan import progress


def _empty_window() -> deque:
    return deque(maxlen=10)


def _stage1_snapshot(
    *,
    target: int = 100,
    inventoried: int = 50,
    pending: int = 50,
    error: int = 0,
    total_findings: int = 1234,
    surfaced: int = 0,
) -> dict:
    return {
        "status": "inventorying",
        "counts": {"inventoried": inventoried, "pending": pending, "error": error},
        "total_findings": total_findings,
        "surfaced": surfaced,
        "median": 0.0,
        "target": target,
        "inv_buckets": {},
    }


def _stage3_snapshot(
    *,
    total_findings: int = 10000,
    pending: int = 6000,
    investigated_no: int = 3000,
    investigated_with: int = 100,
    derived: int = 110,
    skipped_alive: int = 800,
    skipped_language: int = 0,
    skipped_blocklist: int = 0,
) -> dict:
    return {
        "status": "investigating",
        "counts": {"inventoried": 0, "pending": 0, "error": 0},
        "total_findings": total_findings,
        "surfaced": 0,
        "median": 0.0,
        "target": 0,
        "inv_buckets": {
            "pending": pending,
            "investigated_no_candidate": investigated_no,
            "investigated_with_candidate": investigated_with,
            "derived_candidate": derived,
            "skipped_alive": skipped_alive,
            "skipped_language": skipped_language,
            "skipped_blocklist": skipped_blocklist,
        },
    }


# --- Stage 1 ---------------------------------------------------------------


def test_render_stage1_has_canonical_shape() -> None:
    snap = _stage1_snapshot(target=100, inventoried=42, pending=58, error=0, total_findings=3500)
    line = progress.render(
        snap,
        _empty_window(),
        _empty_window(),
        _empty_window(),
        started_mono=time.monotonic() - 60,  # 1 minute ago
    )
    # Expected: [HH:MM:SS] stage1 42/100 (42.0%) inventoried=42 pending=58 err=0
    # findings=3,500 (5m: +0/min) rate=N/min (5m: N/min) ETA=?
    assert re.match(
        r"^\[\d{2}:\d{2}:\d{2}\] stage1 42/100 \(42\.0%\) "
        r"inventoried=42 pending=58 err=0 "
        r"findings=3,500 \(5m: \+0/min\) "
        r"rate=\d+\.\d+/min \(5m: \d+\.\d+/min\) ETA=",
        line,
    ), line


def test_render_stage1_zero_target_does_not_divide_by_zero() -> None:
    snap = _stage1_snapshot(target=0, inventoried=0, pending=0)
    line = progress.render(snap, _empty_window(), _empty_window(), _empty_window(), started_mono=time.monotonic())
    assert "0.0%" in line


# --- Stage 2 ---------------------------------------------------------------


def test_render_stage2_has_canonical_shape() -> None:
    snap = _stage1_snapshot()
    snap["status"] = "checking"
    line = progress.render(snap, _empty_window(), _empty_window(), _empty_window(), started_mono=time.monotonic())
    assert "stage2" in line
    assert "findings=" in line
    assert "(5m:" in line


# --- Stage 3 ---------------------------------------------------------------


def test_render_stage3_has_canonical_shape() -> None:
    snap = _stage3_snapshot(
        total_findings=10000,
        pending=6000,
        investigated_no=3000,
        investigated_with=100,
        derived=110,
        skipped_alive=800,
    )
    line = progress.render(snap, _empty_window(), _empty_window(), _empty_window(), started_mono=time.monotonic())
    # Schema: stage3 4,000/10,000 (40.0%) skipped=800 investigated=3,100 yield=3.2% cands+=110 (5m: +0/min) ETA=?
    assert re.search(
        r"stage3 4,000/10,000 \(40\.0%\) "
        r"skipped=800 investigated=3,100 yield=3\.2% "
        r"cands\+=110 \(5m: ",
        line,
    ), line


def test_render_stage3_yield_n_a_when_no_real_investigations() -> None:
    snap = _stage3_snapshot(
        total_findings=1000,
        pending=1000,
        investigated_no=0,
        investigated_with=0,
        derived=0,
        skipped_alive=0,
    )
    line = progress.render(snap, _empty_window(), _empty_window(), _empty_window(), started_mono=time.monotonic())
    assert "yield=n/a" in line


def test_render_stage3_zero_findings_does_not_divide_by_zero() -> None:
    snap = _stage3_snapshot(total_findings=0, pending=0, investigated_no=0, investigated_with=0, derived=0)
    line = progress.render(snap, _empty_window(), _empty_window(), _empty_window(), started_mono=time.monotonic())
    assert "stage3 0/0 (0.0%)" in line


# --- Stage 4/5 ---------------------------------------------------------------


def test_render_stage4_scoring() -> None:
    snap = _stage1_snapshot()
    snap["status"] = "scoring"
    snap["surfaced"] = 50
    snap["median"] = 0.85
    line = progress.render(snap, _empty_window(), _empty_window(), _empty_window(), started_mono=time.monotonic())
    assert "stage4" in line
    assert "surfaced=50" in line
    assert "sample_median=0.85" in line


def test_render_stage5_done() -> None:
    snap = _stage1_snapshot()
    snap["status"] = "done"
    snap["surfaced"] = 50
    snap["total_findings"] = 100
    line = progress.render(snap, _empty_window(), _empty_window(), _empty_window(), started_mono=time.monotonic())
    assert "stage5" in line
    assert "status=done" in line
    assert "surfaced=50/100" in line


# --- Unknown status fallback ----------------------------------------------


def test_render_unknown_status_does_not_crash() -> None:
    snap = _stage1_snapshot()
    snap["status"] = "nonsense-status"
    line = progress.render(snap, _empty_window(), _empty_window(), _empty_window(), started_mono=time.monotonic())
    assert "status=nonsense-status" in line
    assert "stage unknown" in line


# --- Rate calculation ------------------------------------------------------


def test_rate_returns_zero_with_fewer_than_two_samples() -> None:
    window: deque = deque(maxlen=10)
    assert progress._rate(window) == 0.0
    window.append((100.0, 42))
    assert progress._rate(window) == 0.0


def test_rate_per_minute_over_window() -> None:
    """120 items processed over 1 minute -> 120/min."""
    window: deque = deque(maxlen=10)
    window.append((100.0, 0))
    window.append((160.0, 120))  # 60s later, 120 more items
    rate = progress._rate(window)
    assert abs(rate - 120.0) < 0.01


def test_eta_str_question_mark_when_rate_zero() -> None:
    assert progress._eta_str(100, 0.0) == "?"


def test_eta_str_minutes_when_under_60min() -> None:
    # 100 remaining at 10/min -> 10m
    assert progress._eta_str(100, 10.0) == "10m"


def test_eta_str_hours_when_over_60min() -> None:
    # 6000 remaining at 10/min -> 600m -> 10.0h
    assert progress._eta_str(6000, 10.0) == "10.0h"
