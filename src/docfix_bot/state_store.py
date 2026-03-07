"""Persistent state tracking with TinyDB.

See LLD #2 §2.4 for state_store specification.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from tinydb import TinyDB, where

from docfix_bot.models import PRSubmission, TargetRepository

logger = logging.getLogger(__name__)


class StateStore:
    """TinyDB-backed state store for Doc-Fix Bot."""

    def __init__(self, db_path: Path) -> None:
        """Initialize the state store.

        Args:
            db_path: Path to TinyDB JSON file.
        """
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = TinyDB(str(db_path))
        self._submissions = self._db.table("submissions")
        self._api_calls = self._db.table("api_calls")
        self._scans = self._db.table("scans")

    def record_pr_submission(self, submission: PRSubmission) -> None:
        """Record a submitted PR to prevent duplicates.

        Args:
            submission: The PR submission to record.
        """
        record = dict(submission)
        record["repository"] = dict(submission["repository"])
        record["broken_links_fixed"] = [dict(bl) for bl in submission["broken_links_fixed"]]
        self._submissions.insert(record)

    def was_link_already_fixed(
        self,
        target: TargetRepository,
        url: str,
    ) -> bool:
        """Check if we've already submitted a fix for this link.

        Args:
            target: Repository being checked.
            url: The broken link URL.

        Returns:
            True if a fix was already submitted.
        """
        results = self._submissions.search(
            (where("repository")["owner"] == target["owner"]) & (where("repository")["repo"] == target["repo"])
        )

        for result in results:
            for link in result.get("broken_links_fixed", []):
                if link.get("original_url") == url:
                    return True

        return False

    def get_daily_pr_count(self) -> int:
        """Count PRs submitted today.

        Returns:
            Number of PRs submitted today.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        results = self._submissions.search(where("submitted_at").test(lambda v: v.startswith(today)))
        return len(results)

    def get_hourly_api_count(self) -> int:
        """Count API calls this hour.

        Returns:
            Number of API calls this hour.
        """
        now = datetime.now(timezone.utc)
        hour_prefix = now.strftime("%Y-%m-%dT%H")
        results = self._api_calls.search(where("timestamp").test(lambda v: v.startswith(hour_prefix)))
        return len(results)

    def increment_api_count(self) -> None:
        """Record an API call for rate limiting."""
        self._api_calls.insert(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    def record_scan(
        self,
        target: TargetRepository,
        scan_time: str,
    ) -> None:
        """Record that a repository was scanned.

        Args:
            target: Repository that was scanned.
            scan_time: ISO 8601 timestamp.
        """
        self._scans.insert(
            {
                "owner": target["owner"],
                "repo": target["repo"],
                "scan_time": scan_time,
            }
        )

    def was_recently_scanned(
        self,
        target: TargetRepository,
        hours: int = 24,
    ) -> bool:
        """Check if repository was scanned within the given hours.

        Args:
            target: Repository to check.
            hours: Number of hours to consider "recent".

        Returns:
            True if scanned recently.
        """
        results = self._scans.search((where("owner") == target["owner"]) & (where("repo") == target["repo"]))

        if not results:
            return False

        latest = max(results, key=lambda r: r["scan_time"])
        scan_dt = datetime.fromisoformat(latest["scan_time"])
        now = datetime.now(timezone.utc)
        delta = now - scan_dt
        return delta.total_seconds() < hours * 3600

    def close(self) -> None:
        """Close the database."""
        self._db.close()
