"""Tests for PR outcome tracker.

See Issue #86 for specification.

Note: MetricsCollector and PROutcome are imported inside functions
to avoid the circular import in gh_link_auditor.metrics.__init__.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from gh_link_auditor.pr_tracker import (
    _check_maintainer_fixed,
    _determine_status,
    _fetch_pr_status,
    _parse_iso_datetime,
    _parse_pr_url,
    refresh_pr_outcomes,
)


def _make_outcome(
    pr_url: str = "https://github.com/org/repo/pull/1",
    repo_full_name: str = "org/repo",
    status: str = "open",
    submitted_at: datetime | None = None,
):
    """Create a PROutcome."""
    from gh_link_auditor.metrics.models import PROutcome

    return PROutcome(
        pr_url=pr_url,
        repo_full_name=repo_full_name,
        submitted_at=submitted_at or datetime(2026, 3, 1, tzinfo=timezone.utc),
        status=status,
    )


def _seed_db(db_path: Path, outcomes):
    """Seed database with PR outcomes."""
    from gh_link_auditor.metrics.collector import MetricsCollector

    collector = MetricsCollector(db_path)
    for o in outcomes:
        collector.record_pr_outcome(o)
    collector.close()


class TestParsePrUrl:
    """Tests for _parse_pr_url()."""

    def test_standard_url(self) -> None:
        owner, repo, number = _parse_pr_url("https://github.com/pallets/flask/pull/123")
        assert owner == "pallets"
        assert repo == "flask"
        assert number == 123

    def test_trailing_slash(self) -> None:
        owner, repo, number = _parse_pr_url("https://github.com/org/repo/pull/456/")
        assert owner == "org"
        assert repo == "repo"
        assert number == 456

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse"):
            _parse_pr_url("https://example.com/not-a-pr")

    def test_missing_number_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse"):
            _parse_pr_url("https://github.com/org/repo/pull/abc")


class TestFetchPrStatus:
    """Tests for _fetch_pr_status()."""

    def test_returns_parsed_json(self) -> None:
        mock_result = _mock_completed(
            '{"state": "closed", "merged": true, "merged_at": "2026-03-19T10:00:00Z", "closed_at": null}'
        )
        with patch("subprocess.run", return_value=mock_result):
            data = _fetch_pr_status("org", "repo", 42)
        assert data["state"] == "closed"
        assert data["merged"] is True

    def test_raises_on_failure(self) -> None:
        mock_result = _mock_completed("", returncode=1, stderr="not found")
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="gh api failed"):
                _fetch_pr_status("org", "repo", 999)

    def test_raises_when_gh_not_found(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(RuntimeError, match="gh CLI not found"):
                _fetch_pr_status("org", "repo", 1)


class TestDetermineStatus:
    """Tests for _determine_status()."""

    def test_merged(self) -> None:
        assert _determine_status({"merged": True, "state": "closed"}) == "merged"

    def test_closed_not_merged(self) -> None:
        assert _determine_status({"merged": False, "state": "closed"}) == "closed"

    def test_open(self) -> None:
        assert _determine_status({"merged": False, "state": "open"}) == "open"

    def test_missing_fields_default_open(self) -> None:
        assert _determine_status({}) == "open"


class TestParseIsoDatetime:
    """Tests for _parse_iso_datetime()."""

    def test_standard_iso(self) -> None:
        dt = _parse_iso_datetime("2026-03-19T10:00:00+00:00")
        assert dt is not None
        assert dt.year == 2026

    def test_z_suffix(self) -> None:
        dt = _parse_iso_datetime("2026-03-19T10:00:00Z")
        assert dt is not None

    def test_none_input(self) -> None:
        assert _parse_iso_datetime(None) is None

    def test_empty_string(self) -> None:
        assert _parse_iso_datetime("") is None

    def test_invalid_string(self) -> None:
        assert _parse_iso_datetime("not-a-date") is None


class TestCheckMaintainerFixed:
    """Tests for _check_maintainer_fixed()."""

    def test_detects_fix_keywords(self) -> None:
        pr_body = _mock_completed("some body text")
        commits = _mock_completed("fix broken link in README.md\nupdate docs\n")

        with patch("subprocess.run", side_effect=[pr_body, commits]):
            assert _check_maintainer_fixed("org", "repo", 42) is True

    def test_no_keywords(self) -> None:
        pr_body = _mock_completed("some body text")
        commits = _mock_completed("add new feature\nrelease v2.0\n")

        with patch("subprocess.run", side_effect=[pr_body, commits]):
            assert _check_maintainer_fixed("org", "repo", 42) is False

    def test_handles_api_failure(self) -> None:
        mock_result = _mock_completed("", returncode=1)
        with patch("subprocess.run", return_value=mock_result):
            assert _check_maintainer_fixed("org", "repo", 42) is False

    def test_handles_gh_not_found(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert _check_maintainer_fixed("org", "repo", 42) is False


class TestFetchPrComments:
    """Tests for _fetch_pr_comments() — issue #178."""

    def test_returns_parsed_list(self) -> None:
        from gh_link_auditor.pr_tracker import _fetch_pr_comments

        payload = (
            '[{"id": 1, "body": "thanks", "html_url": "u/1", '
            '"author_association": "OWNER", "created_at": "2026-04-01T00:00:00Z"}]'
        )
        with patch("subprocess.run", return_value=_mock_completed(payload)):
            comments = _fetch_pr_comments("org", "repo", 42)
        assert len(comments) == 1
        assert comments[0]["id"] == 1
        assert comments[0]["author_association"] == "OWNER"

    def test_empty_list(self) -> None:
        from gh_link_auditor.pr_tracker import _fetch_pr_comments

        with patch("subprocess.run", return_value=_mock_completed("[]")):
            assert _fetch_pr_comments("org", "repo", 42) == []

    def test_raises_on_api_failure(self) -> None:
        from gh_link_auditor.pr_tracker import _fetch_pr_comments

        with patch("subprocess.run", return_value=_mock_completed("", returncode=1, stderr="rate limited")):
            with pytest.raises(RuntimeError, match="gh api failed"):
                _fetch_pr_comments("org", "repo", 42)

    def test_raises_when_gh_not_found(self) -> None:
        from gh_link_auditor.pr_tracker import _fetch_pr_comments

        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(RuntimeError, match="gh CLI not found"):
                _fetch_pr_comments("org", "repo", 42)


class TestFindHostileComments:
    """Tests for _find_hostile_comments() — issue #178."""

    def test_no_comments_returns_empty(self) -> None:
        from gh_link_auditor.pr_tracker import _find_hostile_comments

        with patch("gh_link_auditor.pr_tracker._fetch_pr_comments", return_value=[]):
            assert _find_hostile_comments("org", "repo", 1) == []

    def test_non_maintainer_hostile_is_ignored(self) -> None:
        from gh_link_auditor.pr_tracker import _find_hostile_comments

        comments = [
            {
                "id": 1,
                "body": "fuck off",
                "html_url": "u/1",
                "author_association": "CONTRIBUTOR",
                "created_at": "2026-04-01T00:00:00Z",
            }
        ]
        with patch("gh_link_auditor.pr_tracker._fetch_pr_comments", return_value=comments):
            assert _find_hostile_comments("org", "repo", 1) == []

    def test_maintainer_non_hostile_is_ignored(self) -> None:
        from gh_link_auditor.pr_tracker import _find_hostile_comments

        comments = [
            {
                "id": 1,
                "body": "Thanks! Merging.",
                "html_url": "u/1",
                "author_association": "OWNER",
                "created_at": "2026-04-01T00:00:00Z",
            }
        ]
        with patch("gh_link_auditor.pr_tracker._fetch_pr_comments", return_value=comments):
            assert _find_hostile_comments("org", "repo", 1) == []

    def test_maintainer_hostile_is_returned(self) -> None:
        from gh_link_auditor.pr_tracker import _find_hostile_comments

        comments = [
            {
                "id": 1,
                "body": "stop opening prs to my repo",
                "html_url": "u/1",
                "author_association": "OWNER",
                "created_at": "2026-04-01T00:00:00Z",
            }
        ]
        with patch("gh_link_auditor.pr_tracker._fetch_pr_comments", return_value=comments):
            hits = _find_hostile_comments("org", "repo", 1)
        assert len(hits) == 1
        assert hits[0]["html_url"] == "u/1"

    def test_multiple_hostile_returned_oldest_first(self) -> None:
        from gh_link_auditor.pr_tracker import _find_hostile_comments

        comments = [
            {
                "id": 2,
                "body": "spammer go away",
                "html_url": "u/2",
                "author_association": "MEMBER",
                "created_at": "2026-04-05T00:00:00Z",
            },
            {
                "id": 1,
                "body": "fuck off",
                "html_url": "u/1",
                "author_association": "OWNER",
                "created_at": "2026-04-01T00:00:00Z",
            },
        ]
        # `spammer go away` contains 'spammer' which IS in the phrase list.
        with patch("gh_link_auditor.pr_tracker._fetch_pr_comments", return_value=comments):
            hits = _find_hostile_comments("org", "repo", 1)
        assert [h["id"] for h in hits] == [1, 2]

    def test_swallows_api_failure(self) -> None:
        from gh_link_auditor.pr_tracker import _find_hostile_comments

        with patch(
            "gh_link_auditor.pr_tracker._fetch_pr_comments",
            side_effect=RuntimeError("rate limited"),
        ):
            assert _find_hostile_comments("org", "repo", 1) == []


class TestFindAntiAiComments:
    """Tests for _find_anti_ai_comments() — issue #200."""

    def test_no_comments_returns_empty(self) -> None:
        from gh_link_auditor.pr_tracker import _find_anti_ai_comments

        with patch("gh_link_auditor.pr_tracker._fetch_pr_comments", return_value=[]):
            assert _find_anti_ai_comments("org", "repo", 1) == []

    def test_non_maintainer_anti_ai_is_ignored(self) -> None:
        from gh_link_auditor.pr_tracker import _find_anti_ai_comments

        comments = [
            {
                "id": 1,
                "body": "please do not use genAI to generate or submit a PR",
                "html_url": "u/1",
                "author_association": "CONTRIBUTOR",
                "created_at": "2026-04-01T00:00:00Z",
            }
        ]
        with patch("gh_link_auditor.pr_tracker._fetch_pr_comments", return_value=comments):
            assert _find_anti_ai_comments("org", "repo", 1) == []

    def test_pallets_style_polite_rejection_caught(self) -> None:
        """Real-world: davidism's pallets/flask #6019 maintainer comment."""
        from gh_link_auditor.pr_tracker import _find_anti_ai_comments

        comments = [
            {
                "id": 99,
                "body": "Happy to update this, but please do not use genAI to generate or submit a PR.",
                "html_url": "https://github.com/pallets/flask/pull/6019#issuecomment-99",
                "author_association": "MEMBER",
                "created_at": "2026-05-13T14:29:55Z",
            }
        ]
        with patch("gh_link_auditor.pr_tracker._fetch_pr_comments", return_value=comments):
            hits = _find_anti_ai_comments("pallets", "flask", 6019)
        assert len(hits) == 1
        assert hits[0]["id"] == 99

    def test_swallows_api_failure(self) -> None:
        from gh_link_auditor.pr_tracker import _find_anti_ai_comments

        with patch(
            "gh_link_auditor.pr_tracker._fetch_pr_comments",
            side_effect=RuntimeError("rate limited"),
        ):
            assert _find_anti_ai_comments("org", "repo", 1) == []


class TestRefreshPrOutcomes:
    """Tests for refresh_pr_outcomes()."""

    def test_no_open_prs_returns_empty(self, tmp_path: Path) -> None:
        db_path = tmp_path / "metrics.db"
        _seed_db(db_path, [_make_outcome(status="merged")])
        updated = refresh_pr_outcomes(db_path)
        assert updated == []

    def test_updates_merged_pr(self, tmp_path: Path) -> None:
        db_path = tmp_path / "metrics.db"
        _seed_db(
            db_path,
            [
                _make_outcome(pr_url="https://github.com/org/repo/pull/10", status="open"),
            ],
        )

        api_response = {
            "state": "closed",
            "merged": True,
            "merged_at": "2026-03-15T12:00:00Z",
            "closed_at": None,
        }

        with patch(
            "gh_link_auditor.pr_tracker._fetch_pr_status",
            return_value=api_response,
        ):
            updated = refresh_pr_outcomes(db_path)

        assert len(updated) == 1
        assert updated[0].status == "merged"
        assert updated[0].merged_at is not None
        assert updated[0].time_to_merge_hours is not None
        assert updated[0].time_to_merge_hours > 0

    def test_updates_closed_pr(self, tmp_path: Path) -> None:
        db_path = tmp_path / "metrics.db"
        _seed_db(
            db_path,
            [
                _make_outcome(pr_url="https://github.com/org/repo/pull/20", status="open"),
            ],
        )

        api_response = {
            "state": "closed",
            "merged": False,
            "merged_at": None,
            "closed_at": "2026-03-10T08:00:00Z",
        }

        with (
            patch(
                "gh_link_auditor.pr_tracker._fetch_pr_status",
                return_value=api_response,
            ),
            patch(
                "gh_link_auditor.pr_tracker._check_maintainer_fixed",
                return_value=True,
            ),
        ):
            updated = refresh_pr_outcomes(db_path)

        assert len(updated) == 1
        assert updated[0].status == "closed"
        assert updated[0].rejection_reason == "maintainer committed fix directly"

    def test_skips_still_open(self, tmp_path: Path) -> None:
        db_path = tmp_path / "metrics.db"
        _seed_db(
            db_path,
            [
                _make_outcome(pr_url="https://github.com/org/repo/pull/30", status="open"),
            ],
        )

        api_response = {
            "state": "open",
            "merged": False,
            "merged_at": None,
            "closed_at": None,
        }

        with patch(
            "gh_link_auditor.pr_tracker._fetch_pr_status",
            return_value=api_response,
        ):
            updated = refresh_pr_outcomes(db_path)

        assert updated == []

    def test_handles_unparseable_url(self, tmp_path: Path) -> None:
        db_path = tmp_path / "metrics.db"
        _seed_db(db_path, [_make_outcome(pr_url="not-a-valid-url", status="open")])
        updated = refresh_pr_outcomes(db_path)
        assert updated == []

    def test_handles_api_failure_gracefully(self, tmp_path: Path) -> None:
        db_path = tmp_path / "metrics.db"
        _seed_db(
            db_path,
            [
                _make_outcome(pr_url="https://github.com/org/repo/pull/40", status="open"),
            ],
        )

        with patch(
            "gh_link_auditor.pr_tracker._fetch_pr_status",
            side_effect=RuntimeError("API error"),
        ):
            updated = refresh_pr_outcomes(db_path)

        assert updated == []

    def test_persists_updates_to_database(self, tmp_path: Path) -> None:
        db_path = tmp_path / "metrics.db"
        _seed_db(
            db_path,
            [
                _make_outcome(pr_url="https://github.com/org/repo/pull/50", status="open"),
            ],
        )

        api_response = {
            "state": "closed",
            "merged": True,
            "merged_at": "2026-03-18T12:00:00Z",
            "closed_at": None,
        }

        with patch(
            "gh_link_auditor.pr_tracker._fetch_pr_status",
            return_value=api_response,
        ):
            refresh_pr_outcomes(db_path)

        # Verify database was updated
        from gh_link_auditor.metrics.collector import MetricsCollector

        collector = MetricsCollector(db_path)
        outcomes = collector.get_all_pr_outcomes()
        collector.close()

        assert len(outcomes) == 1
        assert outcomes[0].status == "merged"

    def test_multiple_prs_mixed_status(self, tmp_path: Path) -> None:
        db_path = tmp_path / "metrics.db"
        _seed_db(
            db_path,
            [
                _make_outcome(pr_url="https://github.com/org/repo/pull/60", status="open"),
                _make_outcome(pr_url="https://github.com/org/repo/pull/61", status="open"),
                _make_outcome(pr_url="https://github.com/org/repo/pull/62", status="merged"),
            ],
        )

        responses = {
            60: {"state": "closed", "merged": True, "merged_at": "2026-03-15T12:00:00Z", "closed_at": None},
            61: {"state": "open", "merged": False, "merged_at": None, "closed_at": None},
        }

        def fake_fetch(owner, repo, pr_number):
            return responses[pr_number]

        with patch(
            "gh_link_auditor.pr_tracker._fetch_pr_status",
            side_effect=fake_fetch,
        ):
            updated = refresh_pr_outcomes(db_path)

        # Only PR 60 should be updated (61 still open, 62 already merged)
        assert len(updated) == 1
        assert "pull/60" in updated[0].pr_url

    def test_blacklists_on_hostile_comment(self, tmp_path: Path) -> None:
        """Issue #178: hostile maintainer comment auto-blacklists the repo."""
        from gh_link_auditor.unified_db import UnifiedDatabase

        db_path = tmp_path / "metrics.db"
        _seed_db(
            db_path,
            [_make_outcome(pr_url="https://github.com/org/repo/pull/70", status="open")],
        )

        still_open = {"state": "open", "merged": False, "merged_at": None, "closed_at": None}
        hostile_comments = [
            {
                "id": 99,
                "body": "stop opening prs here, please",
                "html_url": "https://github.com/org/repo/pull/70#issuecomment-99",
                "author_association": "OWNER",
                "created_at": "2026-04-01T00:00:00Z",
            }
        ]

        with (
            patch("gh_link_auditor.pr_tracker._fetch_pr_status", return_value=still_open),
            patch("gh_link_auditor.pr_tracker._fetch_pr_comments", return_value=hostile_comments),
        ):
            refresh_pr_outcomes(db_path)

        udb = UnifiedDatabase(db_path)
        try:
            entries = udb.get_blacklist()
            hostile_entries = [e for e in entries if e.repo_url == "https://github.com/org/repo"]
            assert len(hostile_entries) == 1
            assert "comment" in hostile_entries[0].reason.lower()
        finally:
            udb.close()

    def test_hostile_blacklist_is_idempotent(self, tmp_path: Path) -> None:
        """Re-running refresh on already-blacklisted repo doesn't dup the row."""
        from gh_link_auditor.unified_db import UnifiedDatabase

        db_path = tmp_path / "metrics.db"
        _seed_db(
            db_path,
            [_make_outcome(pr_url="https://github.com/org/repo/pull/71", status="open")],
        )

        still_open = {"state": "open", "merged": False, "merged_at": None, "closed_at": None}
        hostile_comments = [
            {
                "id": 100,
                "body": "fuck off",
                "html_url": "https://github.com/org/repo/pull/71#issuecomment-100",
                "author_association": "MEMBER",
                "created_at": "2026-04-01T00:00:00Z",
            }
        ]

        with (
            patch("gh_link_auditor.pr_tracker._fetch_pr_status", return_value=still_open),
            patch("gh_link_auditor.pr_tracker._fetch_pr_comments", return_value=hostile_comments),
        ):
            refresh_pr_outcomes(db_path)
            refresh_pr_outcomes(db_path)

        udb = UnifiedDatabase(db_path)
        try:
            entries = udb.get_blacklist()
            assert len([e for e in entries if e.repo_url == "https://github.com/org/repo"]) == 1
        finally:
            udb.close()

    def test_blacklists_on_anti_ai_comment(self, tmp_path: Path) -> None:
        """Issue #200: anti-AI maintainer comment auto-blacklists with source=anti_ai."""
        from gh_link_auditor.unified_db import UnifiedDatabase

        db_path = tmp_path / "metrics.db"
        _seed_db(
            db_path,
            [
                _make_outcome(
                    pr_url="https://github.com/pallets/flask/pull/6019", repo_full_name="pallets/flask", status="open"
                )
            ],
        )

        still_open = {"state": "open", "merged": False, "merged_at": None, "closed_at": None}
        anti_ai_comments = [
            {
                "id": 99,
                "body": "Happy to update this, but please do not use genAI to generate or submit a PR.",
                "html_url": "https://github.com/pallets/flask/pull/6019#issuecomment-99",
                "author_association": "MEMBER",
                "created_at": "2026-05-13T14:29:55Z",
            }
        ]

        with (
            patch("gh_link_auditor.pr_tracker._fetch_pr_status", return_value=still_open),
            patch("gh_link_auditor.pr_tracker._fetch_pr_comments", return_value=anti_ai_comments),
        ):
            refresh_pr_outcomes(db_path)

        udb = UnifiedDatabase(db_path)
        try:
            entries = udb.get_blacklist()
            anti_ai_entries = [e for e in entries if e.repo_url == "https://github.com/pallets/flask"]
            assert len(anti_ai_entries) == 1
            assert "anti-ai" in anti_ai_entries[0].reason.lower() or "policy" in anti_ai_entries[0].reason.lower()
            # source should be "anti_ai" in the underlying row.
            by_source = udb.get_blacklist_by_source()
            assert by_source.get("anti_ai", 0) >= 1
        finally:
            udb.close()


class TestCmdMetricsRefresh:
    """Tests for cmd_metrics_refresh CLI handler."""

    def test_no_changes(self, tmp_path: Path, capsys) -> None:
        from gh_link_auditor.cli.metrics_cmd import cmd_metrics_refresh
        from gh_link_auditor.metrics.collector import MetricsCollector

        db_path = tmp_path / "metrics.db"
        collector = MetricsCollector(db_path)
        collector.close()

        args = argparse.Namespace(db_path=str(db_path))
        exit_code = cmd_metrics_refresh(args)
        assert exit_code == 0

        captured = capsys.readouterr()
        assert "No PR status changes" in captured.out

    def test_shows_updates(self, tmp_path: Path, capsys) -> None:
        from gh_link_auditor.cli.metrics_cmd import cmd_metrics_refresh

        db_path = tmp_path / "metrics.db"
        _seed_db(
            db_path,
            [
                _make_outcome(pr_url="https://github.com/org/repo/pull/99", status="open"),
            ],
        )

        api_response = {
            "state": "closed",
            "merged": True,
            "merged_at": "2026-03-18T12:00:00Z",
            "closed_at": None,
        }

        with patch(
            "gh_link_auditor.pr_tracker._fetch_pr_status",
            return_value=api_response,
        ):
            args = argparse.Namespace(db_path=str(db_path))
            exit_code = cmd_metrics_refresh(args)

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Updated 1 PR(s)" in captured.out
        assert "merged" in captured.out


# ---- Test helpers ----


class _MockCompletedProcess:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _mock_completed(stdout: str = "", returncode: int = 0, stderr: str = "") -> _MockCompletedProcess:
    return _MockCompletedProcess(stdout=stdout, stderr=stderr, returncode=returncode)
