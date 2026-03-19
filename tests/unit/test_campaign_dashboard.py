"""Tests for campaign dashboard formatting.

See Issue #87 for specification.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from gh_link_auditor.campaign_dashboard import (
    _extract_number,
    _format_duration,
    _format_pr_line,
    _pct,
    _relative_time,
    format_dashboard,
    format_dashboard_json,
)
from gh_link_auditor.metrics.models import CampaignMetrics, PROutcome


def _make_metrics(
    total_runs: int = 5,
    total_repos: int = 12,
    total_prs: int = 8,
    merged: int = 5,
    rejected: int = 2,
    open_prs: int = 1,
    acceptance_rate: float = 0.625,
    avg_ttm: float = 48.0,
    rejection_reasons: dict | None = None,
) -> CampaignMetrics:
    return CampaignMetrics(
        total_runs=total_runs,
        total_repos_processed=total_repos,
        total_prs_submitted=total_prs,
        total_prs_merged=merged,
        total_prs_rejected=rejected,
        total_prs_open=open_prs,
        acceptance_rate=acceptance_rate,
        avg_time_to_merge_hours=avg_ttm,
        rejection_reasons=rejection_reasons or {},
    )


def _make_pr(
    repo: str = "pallets/flask",
    pr_url: str = "https://github.com/pallets/flask/pull/1234",
    status: str = "merged",
    submitted_at: datetime | None = None,
    rejection_reason: str | None = None,
    merged_at: datetime | None = None,
    closed_at: datetime | None = None,
    ttm: float | None = None,
) -> PROutcome:
    return PROutcome(
        repo_full_name=repo,
        pr_url=pr_url,
        status=status,
        submitted_at=submitted_at or datetime(2026, 3, 17, tzinfo=timezone.utc),
        merged_at=merged_at,
        closed_at=closed_at,
        rejection_reason=rejection_reason,
        time_to_merge_hours=ttm,
    )


NOW = datetime(2026, 3, 19, 12, 0, 0, tzinfo=timezone.utc)


class TestPct:
    """Tests for _pct()."""

    def test_nonzero(self) -> None:
        assert _pct(5, 8) == "62.5%"

    def test_zero_total(self) -> None:
        assert _pct(0, 0) == "0.0%"

    def test_hundred_percent(self) -> None:
        assert _pct(10, 10) == "100.0%"

    def test_zero_part(self) -> None:
        assert _pct(0, 5) == "0.0%"


class TestFormatDuration:
    """Tests for _format_duration()."""

    def test_hours_only(self) -> None:
        assert _format_duration(3.5) == "4h"

    def test_days_and_hours(self) -> None:
        assert _format_duration(50) == "2d 2h"

    def test_exact_days(self) -> None:
        assert _format_duration(48) == "2d"

    def test_less_than_day(self) -> None:
        assert _format_duration(23.5) == "24h"


class TestRelativeTime:
    """Tests for _relative_time()."""

    def test_just_now(self) -> None:
        dt = NOW - timedelta(seconds=30)
        assert _relative_time(dt, NOW) == "just now"

    def test_minutes(self) -> None:
        dt = NOW - timedelta(minutes=15)
        assert _relative_time(dt, NOW) == "15m ago"

    def test_hours(self) -> None:
        dt = NOW - timedelta(hours=5)
        assert _relative_time(dt, NOW) == "5h ago"

    def test_days(self) -> None:
        dt = NOW - timedelta(days=3)
        assert _relative_time(dt, NOW) == "3d ago"

    def test_future_shows_just_now(self) -> None:
        dt = NOW + timedelta(hours=1)
        assert _relative_time(dt, NOW) == "just now"


class TestExtractNumber:
    """Tests for _extract_number()."""

    def test_standard_url(self) -> None:
        assert _extract_number("https://github.com/owner/repo/pull/123") == 123

    def test_invalid_url(self) -> None:
        assert _extract_number("not-a-url") == 0

    def test_empty(self) -> None:
        assert _extract_number("") == 0


class TestFormatPrLine:
    """Tests for _format_pr_line()."""

    def test_merged_pr(self) -> None:
        pr = _make_pr(status="merged", submitted_at=NOW - timedelta(days=2))
        line = _format_pr_line(pr, NOW)
        assert "pallets/flask" in line
        assert "#1234" in line
        assert "MERGED" in line
        assert "2d ago" in line

    def test_closed_with_reason(self) -> None:
        pr = _make_pr(
            status="closed",
            rejection_reason="maintainer committed fix directly",
            submitted_at=NOW - timedelta(days=5),
        )
        line = _format_pr_line(pr, NOW)
        assert "CLOSED" in line
        assert "maintainer committed fix directly" in line

    def test_open_pr(self) -> None:
        pr = _make_pr(status="open", submitted_at=NOW - timedelta(hours=12))
        line = _format_pr_line(pr, NOW)
        assert "OPEN" in line
        assert "12h ago" in line


class TestFormatDashboard:
    """Tests for format_dashboard()."""

    def test_header(self) -> None:
        metrics = _make_metrics()
        text = format_dashboard(metrics, [], now=NOW)
        assert "Campaign Summary" in text
        assert "=" * 40 in text

    def test_aggregate_stats(self) -> None:
        metrics = _make_metrics()
        text = format_dashboard(metrics, [], now=NOW)
        assert "Repos scanned:" in text
        assert "12" in text
        assert "PRs submitted:" in text
        assert "8" in text
        assert "PRs merged:" in text
        assert "62.5%" in text

    def test_acceptance_rate(self) -> None:
        metrics = _make_metrics(acceptance_rate=0.625)
        text = format_dashboard(metrics, [], now=NOW)
        assert "62.5%" in text

    def test_avg_time_to_merge(self) -> None:
        metrics = _make_metrics(avg_ttm=48.0)
        text = format_dashboard(metrics, [], now=NOW)
        assert "2d" in text

    def test_rejection_reasons(self) -> None:
        metrics = _make_metrics(rejection_reasons={"maintainer fixed": 2, "stale PR": 1})
        text = format_dashboard(metrics, [], now=NOW)
        assert "Rejection reasons:" in text
        assert "maintainer fixed: 2" in text
        assert "stale PR: 1" in text

    def test_recent_prs_section(self) -> None:
        metrics = _make_metrics()
        prs = [
            _make_pr(
                repo="pallets/flask",
                pr_url="https://github.com/pallets/flask/pull/1234",
                status="merged",
                submitted_at=NOW - timedelta(days=2),
            ),
            _make_pr(
                repo="psf/requests",
                pr_url="https://github.com/psf/requests/pull/567",
                status="closed",
                rejection_reason="maintainer committed fix directly",
                submitted_at=NOW - timedelta(days=5),
            ),
            _make_pr(
                repo="fastapi/fastapi",
                pr_url="https://github.com/fastapi/fastapi/pull/89",
                status="open",
                submitted_at=NOW - timedelta(days=1),
            ),
        ]
        text = format_dashboard(metrics, prs, now=NOW)
        assert "Recent PRs:" in text
        assert "pallets/flask" in text
        assert "psf/requests" in text
        assert "fastapi/fastapi" in text
        assert "MERGED" in text
        assert "CLOSED" in text
        assert "OPEN" in text

    def test_no_recent_prs(self) -> None:
        metrics = _make_metrics()
        text = format_dashboard(metrics, [], now=NOW)
        assert "Recent PRs:" not in text

    def test_limits_to_10_prs(self) -> None:
        metrics = _make_metrics()
        prs = [
            _make_pr(
                pr_url=f"https://github.com/org/repo/pull/{i}",
                submitted_at=NOW - timedelta(days=i),
            )
            for i in range(15)
        ]
        text = format_dashboard(metrics, prs, now=NOW)
        # Count PR lines (lines under "Recent PRs:")
        in_prs = False
        pr_lines = 0
        for line in text.splitlines():
            if line.strip() == "Recent PRs:":
                in_prs = True
                continue
            if in_prs and line.strip():
                pr_lines += 1
        assert pr_lines == 10

    def test_zero_prs_no_division_error(self) -> None:
        metrics = _make_metrics(total_prs=0, merged=0, rejected=0, open_prs=0, acceptance_rate=0.0)
        text = format_dashboard(metrics, [], now=NOW)
        assert "0.0%" in text

    def test_skips_avg_ttm_when_zero(self) -> None:
        metrics = _make_metrics(avg_ttm=0.0)
        text = format_dashboard(metrics, [], now=NOW)
        assert "Avg time to merge" not in text


class TestFormatDashboardJson:
    """Tests for format_dashboard_json()."""

    def test_returns_dict(self) -> None:
        metrics = _make_metrics()
        data = format_dashboard_json(metrics, [])
        assert isinstance(data, dict)
        assert data["total_runs"] == 5
        assert data["total_prs_submitted"] == 8

    def test_includes_recent_prs(self) -> None:
        metrics = _make_metrics()
        prs = [_make_pr()]
        data = format_dashboard_json(metrics, prs)
        assert len(data["recent_prs"]) == 1
        assert data["recent_prs"][0]["repo"] == "pallets/flask"

    def test_pr_fields(self) -> None:
        metrics = _make_metrics()
        prs = [
            _make_pr(
                merged_at=datetime(2026, 3, 18, tzinfo=timezone.utc),
                ttm=24.0,
            )
        ]
        data = format_dashboard_json(metrics, prs)
        pr = data["recent_prs"][0]
        assert pr["status"] == "merged"
        assert pr["merged_at"] is not None
        assert pr["time_to_merge_hours"] == 24.0

    def test_empty_recent_prs(self) -> None:
        metrics = _make_metrics()
        data = format_dashboard_json(metrics, [])
        assert data["recent_prs"] == []
        assert data["rejection_reasons"] == {}
