"""Thin wrapper around UnifiedDatabase for backward compatibility.

Preserves the StateDatabase API so existing consumers (policy_checker,
link_detective, tests) continue to work unchanged.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from gh_link_auditor.models import BlacklistEntry, InteractionRecord, InteractionStatus
from gh_link_auditor.unified_db import UnifiedDatabase


class StateDatabase:
    """Backward-compatible facade delegating to UnifiedDatabase."""

    SCHEMA_VERSION = 2

    def __init__(self, db_path: str = "state.db") -> None:
        self._db = UnifiedDatabase(db_path)
        # Expose _conn for tests that inspect schema directly
        self._conn = self._db._conn

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> StateDatabase:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.close()

    def record_interaction(
        self,
        repo_url: str,
        broken_url: str,
        status: InteractionStatus,
        pr_url: str | None = None,
        maintainer: str | None = None,
        notes: str | None = None,
    ) -> int:
        return self._db.record_interaction(repo_url, broken_url, status, pr_url, maintainer, notes)

    def update_interaction_status(
        self,
        record_id: int,
        new_status: InteractionStatus,
        pr_url: str | None = None,
        notes: str | None = None,
    ) -> bool:
        return self._db.update_interaction_status(record_id, new_status, pr_url, notes)

    def get_interaction(self, repo_url: str, broken_url: str) -> InteractionRecord | None:
        return self._db.get_interaction(repo_url, broken_url)

    def has_been_submitted(self, repo_url: str, broken_url: str) -> bool:
        return self._db.has_been_submitted(repo_url, broken_url)

    def add_to_blacklist(
        self,
        repo_url: str | None = None,
        maintainer: str | None = None,
        reason: str = "",
        expires_at: datetime | None = None,
    ) -> int:
        return self._db.add_to_blacklist(repo_url, maintainer, reason, expires_at)

    def remove_from_blacklist(self, entry_id: int) -> bool:
        return self._db.remove_from_blacklist(entry_id)

    def is_blacklisted(self, repo_url: str, maintainer: str | None = None) -> bool:
        return self._db.is_blacklisted(repo_url, maintainer)

    def get_blacklist(self) -> list[BlacklistEntry]:
        return self._db.get_blacklist()

    def can_submit_fix(self, repo_url: str, broken_url: str, maintainer: str | None = None) -> tuple[bool, str]:
        return self._db.can_submit_fix(repo_url, broken_url, maintainer)

    def get_stats(self) -> dict[str, Any]:
        return self._db.get_stats()
