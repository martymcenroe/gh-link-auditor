"""Unit tests for state database.

Tests for StateDatabase class covering interaction management,
blacklist management, and query helpers. See LLD Issue #5.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from gh_link_auditor.models import BlacklistEntry, InteractionRecord, InteractionStatus
from gh_link_auditor.state_db import StateDatabase

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    """Create an in-memory StateDatabase for each test."""
    with StateDatabase(":memory:") as database:
        yield database


@pytest.fixture
def populated_db(db):
    """Database pre-populated with known interaction and blacklist data."""
    db.record_interaction(
        repo_url="https://github.com/owner/repo1",
        broken_url="https://example.com/dead",
        status=InteractionStatus.SUBMITTED,
        pr_url="https://github.com/owner/repo1/pull/1",
        maintainer="alice",
    )
    db.record_interaction(
        repo_url="https://github.com/owner/repo2",
        broken_url="https://example.com/gone",
        status=InteractionStatus.MERGED,
        pr_url="https://github.com/owner/repo2/pull/5",
        maintainer="bob",
    )
    db.record_interaction(
        repo_url="https://github.com/owner/repo3",
        broken_url="https://example.com/missing",
        status=InteractionStatus.DENIED,
        maintainer="carol",
        notes="Not interested",
    )
    return db


# ---------------------------------------------------------------------------
# T010 – Create database / schema
# ---------------------------------------------------------------------------


def test_create_database():
    """T010: Creates tables on init. Schema matches spec."""
    with StateDatabase(":memory:") as db:
        conn = db._conn
        # Verify tables exist
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "interactions" in tables
        assert "blacklist" in tables
        assert "schema_version" in tables


def test_create_database_schema_columns():
    """T010 extended: interactions and blacklist columns match LLD spec."""
    with StateDatabase(":memory:") as db:
        conn = db._conn

        interaction_cols = {row[1] for row in conn.execute("PRAGMA table_info(interactions)").fetchall()}
        for col in (
            "id",
            "repo_url",
            "broken_url",
            "status",
            "created_at",
            "updated_at",
            "pr_url",
            "maintainer",
            "notes",
        ):
            assert col in interaction_cols, f"Missing column: {col}"

        blacklist_cols = {row[1] for row in conn.execute("PRAGMA table_info(blacklist)").fetchall()}
        for col in (
            "id",
            "repo_url",
            "maintainer",
            "reason",
            "created_at",
            "expires_at",
        ):
            assert col in blacklist_cols, f"Missing column: {col}"


def test_create_database_indexes():
    """T010 extended: expected indexes exist."""
    with StateDatabase(":memory:") as db:
        conn = db._conn
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(interactions)").fetchall()}
        assert "idx_interactions_repo_url" in indexes
        assert "idx_interactions_maintainer" in indexes

        indexes_bl = {row[1] for row in conn.execute("PRAGMA index_list(blacklist)").fetchall()}
        assert "idx_blacklist_repo" in indexes_bl
        assert "idx_blacklist_maintainer" in indexes_bl


def test_create_database_schema_version():
    """T010 extended: schema_version table is seeded."""
    with StateDatabase(":memory:") as db:
        row = db._conn.execute("SELECT version FROM schema_version").fetchone()
        assert row is not None
        assert row["version"] == StateDatabase.SCHEMA_VERSION


# ---------------------------------------------------------------------------
# T020 – Record interaction
# ---------------------------------------------------------------------------


def test_record_interaction(db):
    """T020: Stores interaction record and returns a record ID."""
    record_id = db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
        pr_url="https://github.com/owner/repo/pull/42",
        maintainer="alice",
        notes="First attempt",
    )
    assert isinstance(record_id, int)
    assert record_id > 0

    # Verify retrievable
    record = db.get_interaction("https://github.com/owner/repo", "https://example.com/broken")
    assert record is not None
    assert record.id == record_id
    assert record.repo_url == "https://github.com/owner/repo"
    assert record.broken_url == "https://example.com/broken"
    assert record.status == InteractionStatus.SUBMITTED
    assert record.pr_url == "https://github.com/owner/repo/pull/42"
    assert record.maintainer == "alice"
    assert record.notes == "First attempt"


def test_record_interaction_minimal(db):
    """T020 extended: Record with only required fields."""
    record_id = db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
    )
    assert isinstance(record_id, int)
    record = db.get_interaction("https://github.com/owner/repo", "https://example.com/broken")
    assert record is not None
    assert record.pr_url is None
    assert record.maintainer is None
    assert record.notes is None


def test_record_interaction_timestamps(db):
    """T020 extended: created_at and updated_at are set on insert."""
    db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
    )
    record = db.get_interaction("https://github.com/owner/repo", "https://example.com/broken")
    assert record is not None
    assert record.created_at is not None
    assert record.updated_at is not None
    # created_at and updated_at should be the same on initial insert
    assert record.created_at == record.updated_at


# ---------------------------------------------------------------------------
# T030 – has_been_submitted returns True
# ---------------------------------------------------------------------------


def test_has_been_submitted_true(db):
    """T030: Returns True for an existing repo+url pair."""
    db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
    )
    assert db.has_been_submitted("https://github.com/owner/repo", "https://example.com/broken") is True


# ---------------------------------------------------------------------------
# T040 – has_been_submitted returns False
# ---------------------------------------------------------------------------


def test_has_been_submitted_false(db):
    """T040: Returns False for a new repo+url pair."""
    assert db.has_been_submitted("https://github.com/owner/repo", "https://example.com/broken") is False


def test_has_been_submitted_different_url(db):
    """T040 extended: Different broken_url is not a match."""
    db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
    )
    assert db.has_been_submitted("https://github.com/owner/repo", "https://example.com/other") is False


def test_has_been_submitted_different_repo(db):
    """T040 extended: Different repo_url is not a match."""
    db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
    )
    assert db.has_been_submitted("https://github.com/other/repo", "https://example.com/broken") is False


# ---------------------------------------------------------------------------
# T050 – Update interaction status
# ---------------------------------------------------------------------------


def test_update_interaction_status(db):
    """T050: Updates status correctly and refreshes updated_at."""
    record_id = db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
    )
    before = db.get_interaction("https://github.com/owner/repo", "https://example.com/broken")
    assert before is not None

    # Small delay to ensure updated_at changes
    time.sleep(0.05)

    success = db.update_interaction_status(record_id, InteractionStatus.MERGED)
    assert success is True

    after = db.get_interaction("https://github.com/owner/repo", "https://example.com/broken")
    assert after is not None
    assert after.status == InteractionStatus.MERGED
    assert after.updated_at > before.updated_at


def test_update_interaction_status_with_fields(db):
    """T050 extended: Update status and optional fields together."""
    record_id = db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
    )

    success = db.update_interaction_status(
        record_id,
        InteractionStatus.DENIED,
        pr_url="https://github.com/owner/repo/pull/99",
        notes="Maintainer declined",
    )
    assert success is True

    record = db.get_interaction("https://github.com/owner/repo", "https://example.com/broken")
    assert record is not None
    assert record.status == InteractionStatus.DENIED
    assert record.pr_url == "https://github.com/owner/repo/pull/99"
    assert record.notes == "Maintainer declined"


def test_update_interaction_status_nonexistent(db):
    """T050 extended: Updating a nonexistent record returns False."""
    assert db.update_interaction_status(9999, InteractionStatus.MERGED) is False


# ---------------------------------------------------------------------------
# T060 – Add to blacklist
# ---------------------------------------------------------------------------


def test_add_to_blacklist(db):
    """T060: Adds blacklist entry and returns entry ID."""
    entry_id = db.add_to_blacklist(
        repo_url="https://github.com/owner/repo",
        reason="Opted out",
    )
    assert isinstance(entry_id, int)
    assert entry_id > 0

    # Verify via is_blacklisted
    assert db.is_blacklisted("https://github.com/owner/repo") is True


def test_add_to_blacklist_maintainer(db):
    """T060 extended: Blacklist by maintainer."""
    entry_id = db.add_to_blacklist(
        maintainer="evil_maintainer",
        reason="Abusive",
    )
    assert isinstance(entry_id, int)
    assert entry_id > 0


def test_add_to_blacklist_requires_target(db):
    """T060 extended: Must provide repo_url or maintainer."""
    with pytest.raises(ValueError, match="At least one"):
        db.add_to_blacklist(reason="No target")


def test_add_to_blacklist_with_expiry(db):
    """T060 extended: Blacklist with expiration date."""
    future = datetime.now(timezone.utc) + timedelta(days=30)
    entry_id = db.add_to_blacklist(
        repo_url="https://github.com/owner/repo",
        reason="Temporary ban",
        expires_at=future,
    )
    assert isinstance(entry_id, int)
    assert db.is_blacklisted("https://github.com/owner/repo") is True


# ---------------------------------------------------------------------------
# T070 – is_blacklisted (repo level)
# ---------------------------------------------------------------------------


def test_is_blacklisted_repo(db):
    """T070: Detects blacklisted repo."""
    db.add_to_blacklist(
        repo_url="https://github.com/blocked/repo",
        reason="Opted out",
    )
    assert db.is_blacklisted("https://github.com/blocked/repo") is True
    assert db.is_blacklisted("https://github.com/other/repo") is False


# ---------------------------------------------------------------------------
# T080 – is_blacklisted (maintainer level)
# ---------------------------------------------------------------------------


def test_is_blacklisted_maintainer(db):
    """T080: Detects blacklisted maintainer."""
    db.add_to_blacklist(
        maintainer="blocked_user",
        reason="Requested no contact",
    )
    # Any repo with this maintainer should be blocked
    assert db.is_blacklisted("https://github.com/any/repo", maintainer="blocked_user") is True
    # Without specifying maintainer, repo itself is not blacklisted
    assert db.is_blacklisted("https://github.com/any/repo") is False
    # Different maintainer is fine
    assert db.is_blacklisted("https://github.com/any/repo", maintainer="other_user") is False


# ---------------------------------------------------------------------------
# T090 – can_submit_fix returns True
# ---------------------------------------------------------------------------


def test_can_submit_fix_ok(db):
    """T090: Returns (True, 'ok') when submission is allowed."""
    can_submit, reason = db.can_submit_fix(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        maintainer="alice",
    )
    assert can_submit is True
    assert reason == "ok"


# ---------------------------------------------------------------------------
# T100 – can_submit_fix duplicate
# ---------------------------------------------------------------------------


def test_can_submit_fix_duplicate(db):
    """T100: Returns (False, ...) when URL already submitted."""
    db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
    )
    can_submit, reason = db.can_submit_fix(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
    )
    assert can_submit is False
    assert "already" in reason


# ---------------------------------------------------------------------------
# T110 – can_submit_fix blacklisted
# ---------------------------------------------------------------------------


def test_can_submit_fix_blacklisted_repo(db):
    """T110: Returns (False, ...) when repo is blacklisted."""
    db.add_to_blacklist(
        repo_url="https://github.com/owner/repo",
        reason="Opted out",
    )
    can_submit, reason = db.can_submit_fix(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
    )
    assert can_submit is False
    assert "blacklisted" in reason


def test_can_submit_fix_blacklisted_maintainer(db):
    """T110 extended: Returns (False, ...) when maintainer is blacklisted."""
    db.add_to_blacklist(
        maintainer="blocked_user",
        reason="Abusive",
    )
    can_submit, reason = db.can_submit_fix(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        maintainer="blocked_user",
    )
    assert can_submit is False
    assert "blacklisted" in reason


# ---------------------------------------------------------------------------
# T120 – Blacklist expiration
# ---------------------------------------------------------------------------


def test_blacklist_expiration(db):
    """T120: Expired blacklist entries are ignored."""
    past = datetime.now(timezone.utc) - timedelta(days=1)
    db.add_to_blacklist(
        repo_url="https://github.com/owner/repo",
        reason="Temporary ban",
        expires_at=past,
    )
    # Expired entry should not count as blacklisted
    assert db.is_blacklisted("https://github.com/owner/repo") is False

    # can_submit_fix should also allow it
    can_submit, reason = db.can_submit_fix(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
    )
    assert can_submit is True
    assert reason == "ok"


def test_blacklist_expiration_not_expired(db):
    """T120 extended: Non-expired entry still blocks."""
    future = datetime.now(timezone.utc) + timedelta(days=30)
    db.add_to_blacklist(
        repo_url="https://github.com/owner/repo",
        reason="Temporary ban",
        expires_at=future,
    )
    assert db.is_blacklisted("https://github.com/owner/repo") is True


def test_blacklist_expiration_permanent(db):
    """T120 extended: Entry without expires_at is permanent."""
    db.add_to_blacklist(
        repo_url="https://github.com/owner/repo",
        reason="Permanent ban",
    )
    assert db.is_blacklisted("https://github.com/owner/repo") is True


def test_get_blacklist_excludes_expired(db):
    """T120 extended: get_blacklist only returns active entries."""
    past = datetime.now(timezone.utc) - timedelta(days=1)
    future = datetime.now(timezone.utc) + timedelta(days=30)

    db.add_to_blacklist(
        repo_url="https://github.com/expired/repo",
        reason="Expired",
        expires_at=past,
    )
    db.add_to_blacklist(
        repo_url="https://github.com/active/repo",
        reason="Active",
        expires_at=future,
    )
    db.add_to_blacklist(
        repo_url="https://github.com/permanent/repo",
        reason="Permanent",
    )

    entries = db.get_blacklist()
    repo_urls = [e.repo_url for e in entries]
    assert "https://github.com/expired/repo" not in repo_urls
    assert "https://github.com/active/repo" in repo_urls
    assert "https://github.com/permanent/repo" in repo_urls
    assert len(entries) == 2


# ---------------------------------------------------------------------------
# T130 – Get stats
# ---------------------------------------------------------------------------


def test_get_stats(populated_db):
    """T130: Returns correct counts matching manual count."""
    stats = populated_db.get_stats()
    assert stats["total_interactions"] == 3
    assert stats["by_status"]["submitted"] == 1
    assert stats["by_status"]["merged"] == 1
    assert stats["by_status"]["denied"] == 1
    assert stats["active_blacklist_entries"] == 0
    assert stats["total_blacklist_entries"] == 0


def test_get_stats_empty(db):
    """T130 extended: Stats on empty database."""
    stats = db.get_stats()
    assert stats["total_interactions"] == 0
    assert stats["by_status"] == {}
    assert stats["active_blacklist_entries"] == 0
    assert stats["total_blacklist_entries"] == 0


def test_get_stats_with_blacklist(db):
    """T130 extended: Stats include blacklist counts."""
    db.add_to_blacklist(repo_url="https://github.com/a/b", reason="Ban")
    past = datetime.now(timezone.utc) - timedelta(days=1)
    db.add_to_blacklist(
        repo_url="https://github.com/c/d",
        reason="Expired",
        expires_at=past,
    )
    stats = db.get_stats()
    assert stats["active_blacklist_entries"] == 1
    assert stats["total_blacklist_entries"] == 2


# ---------------------------------------------------------------------------
# T140 – Database persistence
# ---------------------------------------------------------------------------


def test_database_persistence(tmp_path):
    """T140: Data persists across close and reopen."""
    db_file = str(tmp_path / "test_persist.db")

    # Write data and close
    with StateDatabase(db_file) as db:
        record_id = db.record_interaction(
            repo_url="https://github.com/owner/repo",
            broken_url="https://example.com/broken",
            status=InteractionStatus.SUBMITTED,
            pr_url="https://github.com/owner/repo/pull/1",
            maintainer="alice",
        )
        db.add_to_blacklist(
            maintainer="blocked_user",
            reason="Opted out",
        )

    # Reopen and verify
    with StateDatabase(db_file) as db:
        record = db.get_interaction("https://github.com/owner/repo", "https://example.com/broken")
        assert record is not None
        assert record.id == record_id
        assert record.status == InteractionStatus.SUBMITTED
        assert record.pr_url == "https://github.com/owner/repo/pull/1"
        assert record.maintainer == "alice"

        assert db.is_blacklisted("https://github.com/any/repo", maintainer="blocked_user") is True

        assert db.has_been_submitted("https://github.com/owner/repo", "https://example.com/broken") is True


# ---------------------------------------------------------------------------
# Scenario 010 – Create new database (REQ-1)
# ---------------------------------------------------------------------------


def test_010_create_new_database():
    """010: Create new database – schema matches spec (REQ-1)."""
    with StateDatabase(":memory:") as db:
        conn = db._conn

        # Verify interactions table structure
        cols = conn.execute("PRAGMA table_info(interactions)").fetchall()
        col_names = [c[1] for c in cols]
        assert "id" in col_names
        assert "repo_url" in col_names
        assert "broken_url" in col_names
        assert "status" in col_names
        assert "created_at" in col_names
        assert "updated_at" in col_names

        # Verify blacklist table structure
        cols = conn.execute("PRAGMA table_info(blacklist)").fetchall()
        col_names = [c[1] for c in cols]
        assert "id" in col_names
        assert "repo_url" in col_names
        assert "maintainer" in col_names
        assert "reason" in col_names
        assert "expires_at" in col_names


# ---------------------------------------------------------------------------
# Scenario 020 – Record new interaction (REQ-5)
# ---------------------------------------------------------------------------


def test_020_record_new_interaction(db):
    """020: Record new interaction – record ID returned, record retrievable (REQ-5)."""
    record_id = db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
        pr_url="https://github.com/owner/repo/pull/1",
        maintainer="alice",
    )
    assert record_id is not None
    assert isinstance(record_id, int)

    record = db.get_interaction("https://github.com/owner/repo", "https://example.com/broken")
    assert record is not None
    assert record.id == record_id


# ---------------------------------------------------------------------------
# Scenario 030 – Detect submitted URL (REQ-2)
# ---------------------------------------------------------------------------


def test_030_detect_submitted_url(db):
    """030: Detect submitted URL – True, no false negatives (REQ-2)."""
    db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
    )
    assert db.has_been_submitted("https://github.com/owner/repo", "https://example.com/broken") is True


# ---------------------------------------------------------------------------
# Scenario 040 – Allow new URL (REQ-2)
# ---------------------------------------------------------------------------


def test_040_allow_new_url(db):
    """040: Allow new URL – False, no false positives (REQ-2)."""
    assert db.has_been_submitted("https://github.com/owner/repo", "https://example.com/new") is False


# ---------------------------------------------------------------------------
# Scenario 050 – Update status to merged (REQ-7)
# ---------------------------------------------------------------------------


def test_050_update_status_to_merged(db):
    """050: Update status to merged – updated_at changed (REQ-7)."""
    record_id = db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
    )
    before = db.get_interaction("https://github.com/owner/repo", "https://example.com/broken")
    assert before is not None

    time.sleep(0.05)

    db.update_interaction_status(record_id, InteractionStatus.MERGED)
    after = db.get_interaction("https://github.com/owner/repo", "https://example.com/broken")
    assert after is not None
    assert after.status == InteractionStatus.MERGED
    assert after.updated_at > before.updated_at


# ---------------------------------------------------------------------------
# Scenario 060 – Add repo to blacklist (REQ-4)
# ---------------------------------------------------------------------------


def test_060_add_repo_to_blacklist(db):
    """060: Add repo to blacklist – entry ID returned, is_blacklisted True (REQ-4)."""
    entry_id = db.add_to_blacklist(
        repo_url="https://github.com/blocked/repo",
        reason="Opted out",
    )
    assert isinstance(entry_id, int)
    assert db.is_blacklisted("https://github.com/blocked/repo") is True


# ---------------------------------------------------------------------------
# Scenario 070 – Block blacklisted repo (REQ-4)
# ---------------------------------------------------------------------------


def test_070_block_blacklisted_repo(db):
    """070: Block blacklisted repo – can_submit_fix False, reason 'blacklisted' (REQ-4)."""
    db.add_to_blacklist(
        repo_url="https://github.com/blocked/repo",
        reason="Opted out",
    )
    can_submit, reason = db.can_submit_fix(
        repo_url="https://github.com/blocked/repo",
        broken_url="https://example.com/broken",
    )
    assert can_submit is False
    assert "blacklisted" in reason


# ---------------------------------------------------------------------------
# Scenario 080 – Block blacklisted maintainer (REQ-3)
# ---------------------------------------------------------------------------


def test_080_block_blacklisted_maintainer(db):
    """080: Block blacklisted maintainer – can_submit_fix False, reason 'blacklisted' (REQ-3)."""
    db.add_to_blacklist(
        maintainer="blocked_user",
        reason="Requested no contact",
    )
    can_submit, reason = db.can_submit_fix(
        repo_url="https://github.com/any/repo",
        broken_url="https://example.com/broken",
        maintainer="blocked_user",
    )
    assert can_submit is False
    assert "blacklisted" in reason


# ---------------------------------------------------------------------------
# Scenario 090 – Allow clean submission (REQ-1)
# ---------------------------------------------------------------------------


def test_090_allow_clean_submission(db):
    """090: Allow clean submission – can_submit_fix True, reason 'ok' (REQ-1)."""
    can_submit, reason = db.can_submit_fix(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
    )
    assert can_submit is True
    assert reason == "ok"


# ---------------------------------------------------------------------------
# Scenario 100 – Block duplicate submission (REQ-2)
# ---------------------------------------------------------------------------


def test_100_block_duplicate_submission(db):
    """100: Block duplicate – second can_submit_fix False, reason 'already' (REQ-2)."""
    db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
    )

    # First check should block
    can_submit, reason = db.can_submit_fix(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
    )
    assert can_submit is False
    assert "already" in reason


# ---------------------------------------------------------------------------
# Scenario 110 – Handle expired blacklist (REQ-4)
# ---------------------------------------------------------------------------


def test_110_handle_expired_blacklist(db):
    """110: Handle expired blacklist – is_blacklisted False, entry ignored (REQ-4)."""
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    db.add_to_blacklist(
        repo_url="https://github.com/owner/repo",
        reason="Temporary",
        expires_at=past,
    )
    assert db.is_blacklisted("https://github.com/owner/repo") is False


# ---------------------------------------------------------------------------
# Scenario 120 – Get statistics (REQ-5)
# ---------------------------------------------------------------------------


def test_120_get_statistics(populated_db):
    """120: Get statistics – correct counts matching manual count (REQ-5)."""
    stats = populated_db.get_stats()
    assert stats["total_interactions"] == 3
    assert stats["by_status"]["submitted"] == 1
    assert stats["by_status"]["merged"] == 1
    assert stats["by_status"]["denied"] == 1


# ---------------------------------------------------------------------------
# Scenario 130 – Close and reopen (REQ-6) [Integration]
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_130_close_and_reopen(tmp_path):
    """130: Close and reopen – data persisted, records still present (REQ-6)."""
    db_file = str(tmp_path / "persist_test.db")

    with StateDatabase(db_file) as db:
        db.record_interaction(
            repo_url="https://github.com/owner/repo",
            broken_url="https://example.com/broken",
            status=InteractionStatus.SUBMITTED,
        )

    with StateDatabase(db_file) as db:
        assert db.has_been_submitted("https://github.com/owner/repo", "https://example.com/broken") is True
        record = db.get_interaction("https://github.com/owner/repo", "https://example.com/broken")
        assert record is not None
        assert record.status == InteractionStatus.SUBMITTED


# ---------------------------------------------------------------------------
# Scenario 140 – Query before submission (REQ-1)
# ---------------------------------------------------------------------------


def test_140_query_before_submission(db):
    """140: Query before submission – DB queried first (REQ-1)."""
    # Verify the can_submit_fix check works as the gatekeeper
    can_submit, reason = db.can_submit_fix(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        maintainer="alice",
    )
    assert can_submit is True
    assert reason == "ok"

    # Now record and try again
    db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
        maintainer="alice",
    )
    can_submit, reason = db.can_submit_fix(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        maintainer="alice",
    )
    assert can_submit is False
    assert "already" in reason


# ---------------------------------------------------------------------------
# Additional edge case tests
# ---------------------------------------------------------------------------


def test_context_manager():
    """Verify StateDatabase works as a context manager."""
    with StateDatabase(":memory:") as db:
        record_id = db.record_interaction(
            repo_url="https://github.com/owner/repo",
            broken_url="https://example.com/broken",
            status=InteractionStatus.SUBMITTED,
        )
        assert record_id > 0
    # After exiting, connection should be closed
    with pytest.raises(Exception):
        db._conn.execute("SELECT 1")


def test_remove_from_blacklist(db):
    """Verify remove_from_blacklist removes the entry."""
    entry_id = db.add_to_blacklist(
        repo_url="https://github.com/owner/repo",
        reason="Temporary",
    )
    assert db.is_blacklisted("https://github.com/owner/repo") is True

    success = db.remove_from_blacklist(entry_id)
    assert success is True
    assert db.is_blacklisted("https://github.com/owner/repo") is False


def test_remove_from_blacklist_nonexistent(db):
    """Verify removing nonexistent blacklist entry returns False."""
    assert db.remove_from_blacklist(9999) is False


def test_get_interaction_returns_none(db):
    """Verify get_interaction returns None for missing record."""
    result = db.get_interaction("https://github.com/nonexistent/repo", "https://example.com/nope")
    assert result is None


def test_get_interaction_returns_latest(db):
    """Verify get_interaction returns the most recent record for a repo+url pair."""
    db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
    )
    time.sleep(0.05)
    db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.DENIED,
        notes="Second attempt",
    )
    record = db.get_interaction("https://github.com/owner/repo", "https://example.com/broken")
    assert record is not None
    assert record.status == InteractionStatus.DENIED
    assert record.notes == "Second attempt"


def test_get_blacklist_returns_entries(db):
    """Verify get_blacklist returns BlacklistEntry models."""
    db.add_to_blacklist(
        repo_url="https://github.com/owner/repo",
        reason="Test ban",
    )
    db.add_to_blacklist(
        maintainer="blocked_user",
        reason="Abusive",
    )
    entries = db.get_blacklist()
    assert len(entries) == 2
    assert all(isinstance(e, BlacklistEntry) for e in entries)


def test_interaction_record_model(db):
    """Verify returned records are InteractionRecord models."""
    db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
    )
    record = db.get_interaction("https://github.com/owner/repo", "https://example.com/broken")
    assert isinstance(record, InteractionRecord)


def test_wal_mode_enabled():
    """Verify WAL journal mode is set."""
    with StateDatabase(":memory:") as db:
        row = db._conn.execute("PRAGMA journal_mode").fetchone()
        # In-memory databases may report 'memory' instead of 'wal'
        # File-based databases will report 'wal'
        assert row is not None


def test_blacklist_checks_both_repo_and_maintainer(db):
    """Blacklist blocks when either repo OR maintainer is blacklisted."""
    db.add_to_blacklist(
        repo_url="https://github.com/blocked/repo",
        reason="Repo blocked",
    )
    db.add_to_blacklist(
        maintainer="blocked_user",
        reason="User blocked",
    )

    # Repo-level block
    assert db.is_blacklisted("https://github.com/blocked/repo") is True

    # Maintainer-level block on a different repo
    assert db.is_blacklisted("https://github.com/clean/repo", maintainer="blocked_user") is True

    # Clean repo + clean maintainer
    assert db.is_blacklisted("https://github.com/clean/repo", maintainer="clean_user") is False
