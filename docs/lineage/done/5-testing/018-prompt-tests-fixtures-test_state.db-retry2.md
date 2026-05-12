# Implementation Request: tests/fixtures/test_state.db

## Task

Write the complete contents of `tests/fixtures/test_state.db`.

Change type: Add
Description: Test fixture database (empty template)

## LLD Specification

# 5 - Feature: Implement State Database for Governance

<!-- Template Metadata
Last Updated: 2026-02-16
Updated By: Revision to fix mechanical validation errors
Update Reason: Fixed test coverage mapping - all requirements now have corresponding tests
-->

## 1. Context & Goal
* **Issue:** #5
* **Objective:** Implement a SQLite-based state database to track all bot interactions, prevent duplicate submissions, and manage maintainer blacklists
* **Status:** Approved (gemini-3-pro-preview, 2026-02-16)
* **Related Issues:** #8 (JSON Report Schema - provides input data structure)

### Open Questions
*Questions that need clarification before or during implementation. Remove when resolved.*

- [ ] Should the database support concurrent access (multiple bot instances)?
- [ ] What is the retention policy for historical interaction records?
- [ ] Should we implement soft-delete for blacklist entries to allow reinstatement?

## 2. Proposed Changes

*This section is the **source of truth** for implementation. Describe exactly what will be built.*

### 2.1 Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `src/` | Add (Directory) | Create source directory for package |
| `src/gh_link_auditor/` | Add (Directory) | Create package directory |
| `src/gh_link_auditor/__init__.py` | Add | Package init with exports |
| `src/gh_link_auditor/state_db.py` | Add | Core database module with StateDatabase class |
| `src/gh_link_auditor/models.py` | Add | Pydantic models for database entities |
| `tests/unit/test_state_db.py` | Add | Unit tests for state database |
| `tests/fixtures/test_state.db` | Add | Test fixture database (empty template) |
| `pyproject.toml` | Modify | Add pydantic dependency if not present |

### 2.1.1 Path Validation (Mechanical - Auto-Checked)

*Issue #277: Before human or Gemini review, paths are verified programmatically.*

Mechanical validation automatically checks:
- All "Modify" files must exist in repository
- All "Delete" files must exist in repository
- All "Add" files must have existing parent directories
- No placeholder prefixes (`src/`, `lib/`, `app/`) unless directory exists

**Path Validation Notes:**
- `src/` directory does not exist - marked as Add (Directory)
- `src/gh_link_auditor/` directory does not exist - marked as Add (Directory)
- `src/gh_link_auditor/__init__.py` changed from Modify to Add (file does not exist)
- `tests/unit/` exists (confirmed in repository structure)
- `tests/fixtures/` exists (confirmed in repository structure)
- `pyproject.toml` exists at repository root (Modify is valid)

**If validation fails, the LLD is BLOCKED before reaching review.**

### 2.2 Dependencies

*New packages, APIs, or services required.*

```toml
# pyproject.toml additions (if any)
pydantic = "^2.0"
```

Note: SQLite is included in Python's standard library (`sqlite3`), no external dependency needed.

### 2.3 Data Structures

```python
# Pseudocode - NOT implementation
from enum import Enum
from typing import TypedDict
from datetime import datetime

class InteractionStatus(Enum):
    SUBMITTED = "submitted"      # Fix PR submitted, awaiting review
    MERGED = "merged"            # PR was merged
    DENIED = "denied"            # PR was rejected by maintainer
    BLACKLISTED = "blacklisted"  # Repo/maintainer blocked future submissions

class InteractionRecord(TypedDict):
    id: int                      # Auto-increment primary key
    repo_url: str                # Full GitHub repo URL
    broken_url: str              # The broken URL that was fixed
    status: InteractionStatus    # Current status of the interaction
    created_at: datetime         # When the record was created
    updated_at: datetime         # Last modification timestamp
    pr_url: str | None           # PR URL if submitted
    maintainer: str | None       # GitHub username of maintainer
    notes: str | None            # Optional notes (e.g., denial reason)

class BlacklistEntry(TypedDict):
    id: int                      # Auto-increment primary key
    repo_url: str | None         # Specific repo, or None for maintainer-level
    maintainer: str | None       # Maintainer username, or None for repo-level
    reason: str                  # Why blacklisted
    created_at: datetime         # When blacklisted
    expires_at: datetime | None  # Optional expiration (None = permanent)
```

### 2.4 Function Signatures

```python
# Signatures only - implementation in source files

class StateDatabase:
    """SQLite-based state database for tracking bot interactions."""
    
    def __init__(self, db_path: str = "state.db") -> None:
        """Initialize database connection and create tables if needed."""
        ...
    
    def close(self) -> None:
        """Close database connection."""
        ...
    
    # Interaction Management
    def record_interaction(
        self,
        repo_url: str,
        broken_url: str,
        status: InteractionStatus,
        pr_url: str | None = None,
        maintainer: str | None = None,
        notes: str | None = None,
    ) -> int:
        """Record a new interaction. Returns the record ID."""
        ...
    
    def update_interaction_status(
        self,
        record_id: int,
        new_status: InteractionStatus,
        pr_url: str | None = None,
        notes: str | None = None,
    ) -> bool:
        """Update status of an existing interaction. Returns success."""
        ...
    
    def get_interaction(
        self,
        repo_url: str,
        broken_url: str,
    ) -> InteractionRecord | None:
        """Get interaction record for a specific repo/URL combo."""
        ...
    
    def has_been_submitted(
        self,
        repo_url: str,
        broken_url: str,
    ) -> bool:
        """Check if a fix has already been submitted for this URL."""
        ...
    
    # Blacklist Management
    def add_to_blacklist(
        self,
        repo_url: str | None = None,
        maintainer: str | None = None,
        reason: str = "",
        expires_at: datetime | None = None,
    ) -> int:
        """Add repo or maintainer to blacklist. Returns entry ID."""
        ...
    
    def remove_from_blacklist(
        self,
        entry_id: int,
    ) -> bool:
        """Remove entry from blacklist. Returns success."""
        ...
    
    def is_blacklisted(
        self,
        repo_url: str,
        maintainer: str | None = None,
    ) -> bool:
        """Check if repo or maintainer is blacklisted."""
        ...
    
    def get_blacklist(self) -> list[BlacklistEntry]:
        """Get all active blacklist entries."""
        ...
    
    # Query Helpers
    def can_submit_fix(
        self,
        repo_url: str,
        broken_url: str,
        maintainer: str | None = None,
    ) -> tuple[bool, str]:
        """
        Master check before any bot action.
        Returns (can_submit, reason) tuple.
        """
        ...
    
    def get_stats(self) -> dict:
        """Get summary statistics of all interactions."""
        ...
```

### 2.5 Logic Flow (Pseudocode)

```
=== Before Any Bot Action ===
1. Receive (repo_url, broken_url, maintainer) from scan results
2. Call can_submit_fix(repo_url, broken_url, maintainer)
   a. Check is_blacklisted(repo_url, maintainer)
      - IF blacklisted THEN return (False, "blacklisted: {reason}")
   b. Check has_been_submitted(repo_url, broken_url)
      - IF submitted THEN return (False, "already submitted")
   c. Return (True, "ok")
3. IF can_submit is False THEN
   - Skip this fix
   - Log reason
4. ELSE
   - Proceed with fix submission

=== Recording a Submission ===
1. Bot creates PR for broken_url fix
2. Call record_interaction(repo_url, broken_url, SUBMITTED, pr_url, maintainer)
3. Store returned record_id for future updates

=== Updating After Response ===
1. Receive notification (PR merged/denied)
2. Call update_interaction_status(record_id, new_status, notes)
3. IF status == DENIED AND maintainer requested no more contact THEN
   - Call add_to_blacklist(maintainer=maintainer, reason="Opted out")

=== Database Initialization ===
1. Connect to SQLite at db_path
2. IF tables don't exist THEN
   - Create interactions table
   - Create blacklist table
   - Create indexes on (repo_url, broken_url) and (maintainer)
3. Return connection
```

### 2.6 Technical Approach

* **Module:** `src/gh_link_auditor/state_db.py`
* **Pattern:** Repository Pattern with context manager support
* **Key Decisions:**
  - SQLite chosen for simplicity, portability, and zero-config operation
  - Single database file allows easy backup/migration
  - Pydantic models for type safety and validation
  - `can_submit_fix()` as the single entry point for all pre-action checks

### 2.7 Architecture Decisions

*Document key architectural decisions that affect the design.*

| Decision | Options Considered | Choice | Rationale |
|----------|-------------------|--------|-----------|
| Database Engine | SQLite, PostgreSQL, JSON file | SQLite | Zero config, portable, sufficient for expected scale |
| ORM vs Raw SQL | SQLAlchemy, raw sqlite3 | Raw sqlite3 | Minimal dependencies, simple schema |
| Blacklist Granularity | Repo-only, Maintainer-only, Both | Both | Flexibility: block specific repo OR all repos from a maintainer |
| Expiring Blacklists | Permanent only, Expiring allowed | Expiring allowed | Allows temporary cooldowns without manual cleanup |

**Architectural Constraints:**
- Must work with single-instance bot (no distributed locking needed initially)
- Must integrate with JSON report schema from Issue #8 for input data
- Database file location must be configurable for testing

## 3. Requirements

*What must be true when this is done. These become acceptance criteria.*

1. Bot queries the database before EVERY submission attempt
2. Duplicate submissions to the same (repo_url, broken_url) pair are prevented
3. Blacklisted maintainers receive no bot contact regardless of repo
4. Blacklisted repos receive no bot contact regardless of broken URL
5. All interactions are logged with timestamps for audit trail
6. Database persists across bot restarts
7. Status transitions are tracked (submitted → merged/denied)

## 4. Alternatives Considered

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| SQLite local DB | Zero config, portable, fast reads, ACID compliant | Single-instance only, no remote access | **Selected** |
| JSON file | Simplest, human-readable | No ACID, slow for large datasets, race conditions | Rejected |
| PostgreSQL | Scalable, concurrent, remote access | Requires server setup, overkill for MVP | Rejected |
| Redis | Fast, good for caching | Requires server, persistence config, overkill | Rejected |

**Rationale:** SQLite provides the best balance of simplicity, reliability, and functionality for a single-instance bot. Can migrate to PostgreSQL later if multi-instance support is needed.

## 5. Data & Fixtures

*Per [0108-lld-pre-implementation-review.md](0108-lld-pre-implementation-review.md) - complete this section BEFORE implementation.*

### 5.1 Data Sources

| Attribute | Value |
|-----------|-------|
| Source | Bot runtime (interactions created by bot operations) |
| Format | SQLite database file |
| Size | ~10KB base + ~1KB per 100 interactions |
| Refresh | Real-time (writes on each interaction) |
| Copyright/License | N/A (generated data) |

### 5.2 Data Pipeline

```
Scan Results (JSON #8) ──query──► StateDatabase ──decision──► Bot Action
                                       ▲
Bot Action Result ──record──────────────┘
```

### 5.3 Test Fixtures

| Fixture | Source | Notes |
|---------|--------|-------|
| Empty test database | Generated | Created fresh for each test |
| Seeded test database | Generated | Pre-populated with known interactions |
| Sample interaction data | Hardcoded | Test vectors for various status combinations |

### 5.4 Deployment Pipeline

- **Dev:** SQLite file in project directory (`./state.db`)
- **Test:** In-memory SQLite (`:memory:`) or temp file
- **Production:** Configurable path, default `~/.gh-link-auditor/state.db`

**If data source is external:** No external data utility needed.

## 6. Diagram

### 6.1 Mermaid Quality Gate

Before finalizing any diagram, verify in [Mermaid Live Editor](https://mermaid.live) or GitHub preview:

- [x] **Simplicity:** Similar components collapsed (per 0006 §8.1)
- [x] **No touching:** All elements have visual separation (per 0006 §8.2)
- [x] **No hidden lines:** All arrows fully visible (per 0006 §8.3)
- [x] **Readable:** Labels not truncated, flow direction clear
- [ ] **Auto-inspected:** Agent rendered via mermaid.ink and viewed (per 0006 §8.5)

**Auto-Inspection Results:**
```
- Touching elements: [ ] None / [ ] Found: ___
- Hidden lines: [ ] None / [ ] Found: ___
- Label readability: [ ] Pass / [ ] Issue: ___
- Flow clarity: [ ] Clear / [ ] Issue: ___
```

*Reference: [0006-mermaid-diagrams.md](0006-mermaid-diagrams.md)*

### 6.2 Diagram

```mermaid
erDiagram
    interactions {
        int id PK
        string repo_url
        string broken_url
        string status
        datetime created_at
        datetime updated_at
        string pr_url
        string maintainer
        string notes
    }
    
    blacklist {
        int id PK
        string repo_url
        string maintainer
        string reason
        datetime created_at
        datetime expires_at
    }
```

```mermaid
sequenceDiagram
    participant Bot
    participant StateDB
    participant GitHub

    Bot->>StateDB: can_submit_fix(repo, url, maintainer)
    StateDB->>StateDB: Check blacklist
    StateDB->>StateDB: Check duplicates
    StateDB-->>Bot: (True, "ok")
    
    Bot->>GitHub: Create PR
    GitHub-->>Bot: PR URL
    
    Bot->>StateDB: record_interaction(repo, url, SUBMITTED, pr_url)
    StateDB-->>Bot: record_id
    
    Note over Bot,GitHub: Later...
    
    GitHub-->>Bot: PR merged notification
    Bot->>StateDB: update_interaction_status(record_id, MERGED)
```

## 7. Security & Safety Considerations

### 7.1 Security

| Concern | Mitigation | Status |
|---------|------------|--------|
| SQL Injection | Parameterized queries only (no string concatenation) | Addressed |
| Database file permissions | Create with restrictive permissions (0600) | Addressed |
| Sensitive data exposure | No credentials stored in DB; only URLs and usernames | Addressed |

### 7.2 Safety

| Concern | Mitigation | Status |
|---------|------------|--------|
| Data loss on crash | SQLite WAL mode for durability | Addressed |
| Accidental blacklist deletion | Soft-delete consideration (future enhancement) | Pending |
| Concurrent access corruption | Single-instance constraint documented | Addressed |
| DB file deletion | Warn on missing DB, don't auto-recreate in production | Addressed |

**Fail Mode:** Fail Closed - If database is unavailable, bot refuses to submit any fixes (prevents duplicates)

**Recovery Strategy:** 
- Database backup before major operations
- Export/import functions for migration
- If corrupted, restore from backup; any gaps are acceptable (may cause one duplicate)

## 8. Performance & Cost Considerations

### 8.1 Performance

| Metric | Budget | Approach |
|--------|--------|----------|
| Query latency | < 10ms | Indexed queries, local SQLite |
| Memory | < 10MB | SQLite with small page cache |
| Write durability | < 100ms | WAL mode with checkpoint |

**Bottlenecks:** 
- Full table scans on blacklist (mitigated by expected small size < 1000 entries)
- Index on (repo_url, broken_url) for fast duplicate checks

### 8.2 Cost Analysis

| Resource | Unit Cost | Estimated Usage | Monthly Cost |
|----------|-----------|-----------------|--------------|
| Storage | $0 | < 10MB local | $0 |
| Compute | $0 | Local execution | $0 |

**Cost Controls:**
- N/A - No external costs

**Worst-Case Scenario:** Database grows to 100MB with 100K interactions. SQLite handles this easily. Archive old completed interactions if needed.

## 9. Legal & Compliance

| Concern | Applies? | Mitigation |
|---------|----------|------------|
| PII/Personal Data | Yes | Only GitHub usernames (public data) stored |
| Third-Party Licenses | No | N/A |
| Terms of Service | Yes | GitHub ToS allows storing public usernames |
| Data Retention | Yes | Consider auto-purge of records > 1 year old |
| Export Controls | No | N/A |

**Data Classification:** Internal

**Compliance Checklist:**
- [x] No PII stored without consent (usernames are public GitHub data)
- [x] All third-party licenses compatible with project license
- [x] External API usage compliant with provider ToS
- [ ] Data retention policy documented (to be added)

## 10. Verification & Testing

*Ref: [0005-testing-strategy-and-protocols.md](0005-testing-strategy-and-protocols.md)*

**Testing Philosophy:** Strive for 100% automated test coverage. Manual tests are a last resort.

### 10.0 Test Plan (TDD - Complete Before Implementation)

**TDD Requirement:** Tests MUST be written and failing BEFORE implementation begins.

| Test ID | Test Description | Expected Behavior | Status |
|---------|------------------|-------------------|--------|
| T010 | test_create_database | Creates tables on init | RED |
| T020 | test_record_interaction | Stores interaction record | RED |
| T030 | test_has_been_submitted_true | Returns True for existing | RED |
| T040 | test_has_been_submitted_false | Returns False for new | RED |
| T050 | test_update_interaction_status | Updates status correctly | RED |
| T060 | test_add_to_blacklist | Adds blacklist entry | RED |
| T070 | test_is_blacklisted_repo | Detects blacklisted repo | RED |
| T080 | test_is_blacklisted_maintainer | Detects blacklisted maintainer | RED |
| T090 | test_can_submit_fix_ok | Returns True when allowed | RED |
| T100 | test_can_submit_fix_duplicate | Returns False for duplicate | RED |
| T110 | test_can_submit_fix_blacklisted | Returns False for blacklisted | RED |
| T120 | test_blacklist_expiration | Expired entries ignored | RED |
| T130 | test_get_stats | Returns correct counts | RED |
| T140 | test_database_persistence | Data persists across restarts | RED |

**Coverage Target:** ≥95% for all new code

**TDD Checklist:**
- [ ] All tests written before implementation
- [ ] Tests currently RED (failing)
- [ ] Test IDs match scenario IDs in 10.1
- [ ] Test file created at: `tests/unit/test_state_db.py`

### 10.1 Test Scenarios

| ID | Scenario | Type | Input | Expected Output | Pass Criteria |
|----|----------|------|-------|-----------------|---------------|
| 010 | Create new database (REQ-1) | Auto | Empty path | Tables created | Schema matches spec |
| 020 | Record new interaction (REQ-5) | Auto | Valid interaction data | Record ID returned | Record retrievable |
| 030 | Detect submitted URL (REQ-2) | Auto | Existing repo+url | True | No false negatives |
| 040 | Allow new URL (REQ-2) | Auto | New repo+url | False | No false positives |
| 050 | Update status to merged (REQ-7) | Auto | Record ID + MERGED | Status updated | updated_at changed |
| 060 | Add repo to blacklist (REQ-4) | Auto | Repo URL | Entry ID returned | is_blacklisted returns True |
| 070 | Block blacklisted repo (REQ-4) | Auto | Blacklisted repo | can_submit_fix False | Reason includes "blacklisted" |
| 080 | Block blacklisted maintainer (REQ-3) | Auto | Blacklisted maintainer | can_submit_fix False | Reason includes "blacklisted" |
| 090 | Allow clean submission (REQ-1) | Auto | New repo, no blacklist | can_submit_fix True | Reason is "ok" |
| 100 | Block duplicate submission (REQ-2) | Auto | Same repo+url twice | Second can_submit_fix False | Reason includes "already" |
| 110 | Handle expired blacklist (REQ-4) | Auto | Expired entry | is_blacklisted False | Entry ignored |
| 120 | Get statistics (REQ-5) | Auto | Populated DB | Correct counts | Matches manual count |
| 130 | Close and reopen (REQ-6) | Integration | DB path | Data persisted | Records still present |
| 140 | Query before submission (REQ-1) | Auto | Any submission attempt | DB queried first | Query logged/traced |

### 10.2 Test Commands

```bash
# Run all automated tests
poetry run pytest tests/unit/test_state_db.py -v

# Run with coverage
poetry run pytest tests/unit/test_state_db.py -v --cov=src/gh_link_auditor/state_db

# Run specific test
poetry run pytest tests/unit/test_state_db.py::test_can_submit_fix_ok -v
```

### 10.3 Manual Tests (Only If Unavoidable)

N/A - All scenarios automated.

## 11. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Database corruption | High | Low | WAL mode, regular backups, fail-closed |
| Concurrent access conflicts | Medium | Low | Document single-instance constraint |
| Schema migration needed later | Medium | Medium | Include version table, migration functions |
| SQLite version incompatibility | Low | Low | Use standard sqlite3 features only |

## 12. Definition of Done

### Code
- [ ] Implementation complete and linted
- [ ] Code comments reference this LLD

### Tests
- [ ] All test scenarios pass
- [ ] Test coverage meets threshold (≥95%)

### Documentation
- [ ] LLD updated with any deviations
- [ ] Implementation Report (0103) completed
- [ ] Test Report (0113) completed if applicable

### Review
- [ ] Code review completed
- [ ] User approval before closing issue

### 12.1 Traceability (Mechanical - Auto-Checked)

*Issue #277: Cross-references are verified programmatically.*

Files in Definition of Done must appear in Section 2.1:
- `src/gh_link_auditor/state_db.py` ✓
- `src/gh_link_auditor/models.py` ✓
- `tests/unit/test_state_db.py` ✓

Risk mitigations traced to functions:
- WAL mode → `__init__` connection setup
- fail-closed → `can_submit_fix` returns (False, "db unavailable")

---

## Reviewer Suggestions

*Non-blocking recommendations from the reviewer.*

- **Configuration:** Ensure the default database path in the application code respects the user's environment or defaults to the current working directory during development to avoid writing to `~` (home dir) unexpectedly during local testing, even though production config suggests `~/.gh-link-auditor`.
- **Schema Evolution:** Consider adding a `schema_version` table immediately to simplify future migrations (Section 11 mentions this as a risk/mitigation, but including it in `__init__` now is zero cost).

## Appendix: Review Log

*Track all review feedback with timestamps and implementation status.*

### Review Summary

| Review | Date | Verdict | Key Issue |
|--------|------|---------|-----------|
| 1 | 2026-02-16 | APPROVED | `gemini-3-pro-preview` |
| - | - | - | - |

**Final Status:** APPROVED

## Required File Paths (from LLD - do not deviate)

The following paths are specified in the LLD. Write ONLY to these paths:

- `src`
- `src/gh_link_auditor`
- `src/gh_link_auditor/__init__.py`
- `src/gh_link_auditor/models.py`
- `src/gh_link_auditor/state_db.py`
- `tests/fixtures/test_state.db`
- `tests/unit/test_state_db.py`
- `pyproject.toml`

Any files written to other paths will be rejected.

## Tests That Must Pass

```python
# From C:\Users\mcwiz\Projects\gh-link-auditor\tests\test_issue_5.py
"""Test file for Issue #5.

Generated by AssemblyZero TDD Testing Workflow.
Tests will fail with ImportError until implementation exists (TDD RED phase).
"""

import pytest

# TDD: This import fails until implementation exists (RED phase)
# Once implemented, tests can run (GREEN phase)
from gh_link_auditor.state_db import *  # noqa: F401, F403


# Fixtures for mocking
@pytest.fixture
def mock_external_service():
    """Mock external service for isolation."""
    # TODO: Implement mock
    yield None


# Integration/E2E fixtures
@pytest.fixture
def test_client():
    """Test client for API calls."""
    # TODO: Implement test client
    yield None


# Unit Tests
# -----------

def test_id():
    """
    Test Description | Expected Behavior | Status
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_id works correctly
    assert False, 'TDD RED: test_id not implemented'


def test_t010(mock_external_service):
    """
    test_create_database | Creates tables on init | RED
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_t010 works correctly
    assert False, 'TDD RED: test_t010 not implemented'


def test_t020():
    """
    test_record_interaction | Stores interaction record | RED
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_t020 works correctly
    assert False, 'TDD RED: test_t020 not implemented'


def test_t030():
    """
    test_has_been_submitted_true | Returns True for existing | RED
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_t030 works correctly
    assert False, 'TDD RED: test_t030 not implemented'


def test_t040():
    """
    test_has_been_submitted_false | Returns False for new | RED
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_t040 works correctly
    assert False, 'TDD RED: test_t040 not implemented'


def test_t050():
    """
    test_update_interaction_status | Updates status correctly | RED
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_t050 works correctly
    assert False, 'TDD RED: test_t050 not implemented'


def test_t060():
    """
    test_add_to_blacklist | Adds blacklist entry | RED
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_t060 works correctly
    assert False, 'TDD RED: test_t060 not implemented'


def test_t070():
    """
    test_is_blacklisted_repo | Detects blacklisted repo | RED
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_t070 works correctly
    assert False, 'TDD RED: test_t070 not implemented'


def test_t080():
    """
    test_is_blacklisted_maintainer | Detects blacklisted maintainer | RED
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_t080 works correctly
    assert False, 'TDD RED: test_t080 not implemented'


def test_t090():
    """
    test_can_submit_fix_ok | Returns True when allowed | RED
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_t090 works correctly
    assert False, 'TDD RED: test_t090 not implemented'


def test_t100():
    """
    test_can_submit_fix_duplicate | Returns False for duplicate | RED
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_t100 works correctly
    assert False, 'TDD RED: test_t100 not implemented'


def test_t110():
    """
    test_can_submit_fix_blacklisted | Returns False for blacklisted | RED
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_t110 works correctly
    assert False, 'TDD RED: test_t110 not implemented'


def test_t120():
    """
    test_blacklist_expiration | Expired entries ignored | RED
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_t120 works correctly
    assert False, 'TDD RED: test_t120 not implemented'


def test_t130():
    """
    test_get_stats | Returns correct counts | RED
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_t130 works correctly
    assert False, 'TDD RED: test_t130 not implemented'


def test_t140(mock_external_service):
    """
    test_database_persistence | Data persists across restarts | RED
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_t140 works correctly
    assert False, 'TDD RED: test_t140 not implemented'


def test_010(mock_external_service):
    """
    Create new database (REQ-1) | Auto | Empty path | Tables created |
    Schema matches spec
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_010 works correctly
    assert False, 'TDD RED: test_010 not implemented'


def test_020():
    """
    Record new interaction (REQ-5) | Auto | Valid interaction data |
    Record ID returned | Record retrievable
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_020 works correctly
    assert False, 'TDD RED: test_020 not implemented'


def test_030():
    """
    Detect submitted URL (REQ-2) | Auto | Existing repo+url | True | No
    false negatives
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_030 works correctly
    assert False, 'TDD RED: test_030 not implemented'


def test_040():
    """
    Allow new URL (REQ-2) | Auto | New repo+url | False | No false
    positives
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_040 works correctly
    assert False, 'TDD RED: test_040 not implemented'


def test_050():
    """
    Update status to merged (REQ-7) | Auto | Record ID + MERGED | Status
    updated | updated_at changed
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_050 works correctly
    assert False, 'TDD RED: test_050 not implemented'


def test_060():
    """
    Add repo to blacklist (REQ-4) | Auto | Repo URL | Entry ID returned |
    is_blacklisted returns True
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_060 works correctly
    assert False, 'TDD RED: test_060 not implemented'


def test_070():
    """
    Block blacklisted repo (REQ-4) | Auto | Blacklisted repo |
    can_submit_fix False | Reason includes "blacklisted"
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_070 works correctly
    assert False, 'TDD RED: test_070 not implemented'


def test_080():
    """
    Block blacklisted maintainer (REQ-3) | Auto | Blacklisted maintainer
    | can_submit_fix False | Reason includes "blacklisted"
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_080 works correctly
    assert False, 'TDD RED: test_080 not implemented'


def test_090():
    """
    Allow clean submission (REQ-1) | Auto | New repo, no blacklist |
    can_submit_fix True | Reason is "ok"
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_090 works correctly
    assert False, 'TDD RED: test_090 not implemented'


def test_100():
    """
    Block duplicate submission (REQ-2) | Auto | Same repo+url twice |
    Second can_submit_fix False | Reason includes "already"
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_100 works correctly
    assert False, 'TDD RED: test_100 not implemented'


def test_110():
    """
    Handle expired blacklist (REQ-4) | Auto | Expired entry |
    is_blacklisted False | Entry ignored
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_110 works correctly
    assert False, 'TDD RED: test_110 not implemented'


def test_120():
    """
    Get statistics (REQ-5) | Auto | Populated DB | Correct counts |
    Matches manual count
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_120 works correctly
    assert False, 'TDD RED: test_120 not implemented'


def test_140():
    """
    Query before submission (REQ-1) | Auto | Any submission attempt | DB
    queried first | Query logged/traced
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_140 works correctly
    assert False, 'TDD RED: test_140 not implemented'



# Integration Tests
# -----------------

@pytest.mark.integration
def test_130(test_client):
    """
    Close and reopen (REQ-6) | Integration | DB path | Data persisted |
    Records still present
    """
    # TDD: Arrange
    # Set up test data

    # TDD: Act
    # Call the function under test

    # TDD: Assert
    # Verify test_130 works correctly
    assert False, 'TDD RED: test_130 not implemented'




```

## Previously Implemented Files

These files have already been implemented. Use them for imports and references:

### src/gh_link_auditor/__init__.py (signatures)

```python
"""gh-link-auditor: GitHub broken link auditor with state tracking."""

from gh_link_auditor.models import (
    BlacklistEntry,
    InteractionRecord,
    InteractionStatus,
)

from gh_link_auditor.state_db import StateDatabase

__all__ = [
    "BlacklistEntry",
    "InteractionRecord",
    "InteractionStatus",
    "StateDatabase",
]
```

### src/gh_link_auditor/state_db.py (signatures)

```python
"""Core database module with StateDatabase class.

Implements SQLite-based state tracking for bot interactions and maintainer blacklists.
See LLD Issue #5 for full specification.
"""

from __future__ import annotations

import sqlite3

from datetime import datetime, timezone

from typing import Any

from gh_link_auditor.models import BlacklistEntry, InteractionRecord, InteractionStatus

class StateDatabase:

    """SQLite-based state database for tracking bot interactions."""

    def __init__(self, db_path: str = "state.db") -> None:
    """Initialize database connection and create tables if needed.

Args:"""
    ...

    def _create_tables(self) -> None:
    """Create database tables and indexes if they don't exist."""
    ...

    def close(self) -> None:
    """Close database connection."""
    ...

    def __enter__(self) -> StateDatabase:
    """Support context manager usage."""
    ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
    """Close on context manager exit."""
    ...

    def record_interaction(
        self,
        repo_url: str,
        broken_url: str,
        status: InteractionStatus,
        pr_url: str | None = None,
        maintainer: str | None = None,
        notes: str | None = None,
    ) -> int:
    """Record a new interaction. Returns the record ID."""
    ...

    def update_interaction_status(
        self,
        record_id: int,
        new_status: InteractionStatus,
        pr_url: str | None = None,
        notes: str | None = None,
    ) -> bool:
    """Update status of an existing interaction. Returns success."""
    ...

    def get_interaction(
        self,
        repo_url: str,
        broken_url: str,
    ) -> InteractionRecord | None:
    """Get interaction record for a specific repo/URL combo."""
    ...

    def has_been_submitted(
        self,
        repo_url: str,
        broken_url: str,
    ) -> bool:
    """Check if a fix has already been submitted for this URL."""
    ...

    def add_to_blacklist(
        self,
        repo_url: str | None = None,
        maintainer: str | None = None,
        reason: str = "",
        expires_at: datetime | None = None,
    ) -> int:
    """Add repo or maintainer to blacklist. Returns entry ID."""
    ...

    def remove_from_blacklist(
        self,
        entry_id: int,
    ) -> bool:
    """Remove entry from blacklist. Returns success."""
    ...

    def is_blacklisted(
        self,
        repo_url: str,
        maintainer: str | None = None,
    ) -> bool:
    """Check if repo or maintainer is blacklisted.

Checks for:"""
    ...

    def get_blacklist(self) -> list[BlacklistEntry]:
    """Get all active (non-expired) blacklist entries."""
    ...

    def can_submit_fix(
        self,
        repo_url: str,
        broken_url: str,
        maintainer: str | None = None,
    ) -> tuple[bool, str]:
    """Master check before any bot action.

Returns (can_submit, reason) tuple."""
    ...

    def get_stats(self) -> dict[str, Any]:
    """Get summary statistics of all interactions."""
    ...

def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    ...

def _row_to_interaction(row: sqlite3.Row) -> InteractionRecord:
    """Convert a database row to an InteractionRecord."""
    ...

def _row_to_blacklist(row: sqlite3.Row) -> BlacklistEntry:
    """Convert a database row to a BlacklistEntry."""
    ...
```

### src/gh_link_auditor/models.py (signatures)

```python
"""Pydantic models for database entities.

Defines InteractionRecord, BlacklistEntry, and InteractionStatus
for the state database. See LLD Issue #5 for full specification.
"""

from __future__ import annotations

from datetime import datetime

from enum import Enum

from pydantic import BaseModel

class InteractionStatus(str, Enum):

    """Status of a bot interaction with a repository."""

class InteractionRecord(BaseModel):

    """Record of a bot interaction (fix submission) with a repository."""

class BlacklistEntry(BaseModel):

    """Entry in the maintainer/repo blacklist."""
```

### tests/unit/test_state_db.py (full)

```python
"""Unit tests for state database.

Tests for StateDatabase class covering interaction management,
blacklist management, and query helpers. See LLD Issue #5.
"""

from __future__ import annotations

import sqlite3
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
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "interactions" in tables
        assert "blacklist" in tables
        assert "schema_version" in tables


def test_create_database_schema_columns():
    """T010 extended: interactions and blacklist columns match LLD spec."""
    with StateDatabase(":memory:") as db:
        conn = db._conn

        interaction_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(interactions)").fetchall()
        }
        for col in (
            "id", "repo_url", "broken_url", "status",
            "created_at", "updated_at", "pr_url", "maintainer", "notes",
        ):
            assert col in interaction_cols, f"Missing column: {col}"

        blacklist_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(blacklist)").fetchall()
        }
        for col in (
            "id", "repo_url", "maintainer", "reason",
            "created_at", "expires_at",
        ):
            assert col in blacklist_cols, f"Missing column: {col}"


def test_create_database_indexes():
    """T010 extended: expected indexes exist."""
    with StateDatabase(":memory:") as db:
        conn = db._conn
        indexes = {
            row[1]
            for row in conn.execute("PRAGMA index_list(interactions)").fetchall()
        }
        assert "idx_interactions_repo_url" in indexes
        assert "idx_interactions_maintainer" in indexes

        indexes_bl = {
            row[1]
            for row in conn.execute("PRAGMA index_list(blacklist)").fetchall()
        }
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
    record = db.get_interaction(
        "https://github.com/owner/repo", "https://example.com/broken"
    )
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
    record = db.get_interaction(
        "https://github.com/owner/repo", "https://example.com/broken"
    )
    assert record is not None
    assert record.pr_url is None
    assert record.maintainer is None
    assert record.notes is None


def test_record_interaction_timestamps(db):
    """T020 extended: created_at and updated_at are set on insert."""
    record_id = db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
    )
    record = db.get_interaction(
        "https://github.com/owner/repo", "https://example.com/broken"
    )
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
    assert db.has_been_submitted(
        "https://github.com/owner/repo", "https://example.com/broken"
    ) is True


# ---------------------------------------------------------------------------
# T040 – has_been_submitted returns False
# ---------------------------------------------------------------------------


def test_has_been_submitted_false(db):
    """T040: Returns False for a new repo+url pair."""
    assert db.has_been_submitted(
        "https://github.com/owner/repo", "https://example.com/broken"
    ) is False


def test_has_been_submitted_different_url(db):
    """T040 extended: Different broken_url is not a match."""
    db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
    )
    assert db.has_been_submitted(
        "https://github.com/owner/repo", "https://example.com/other"
    ) is False


def test_has_been_submitted_different_repo(db):
    """T040 extended: Different repo_url is not a match."""
    db.record_interaction(
        repo_url="https://github.com/owner/repo",
        broken_url="https://example.com/broken",
        status=InteractionStatus.SUBMITTED,
    )
    assert db.has_been_submitted(
        "https://github.com/other/repo", "https://example.com/broken"
    ) is False


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
    before = db.get_interaction(
        "https://github.com/owner/repo", "https://example.com/broken"
    )
    assert before is not None

    # Small delay to ensure updated_at changes
    time.sleep(0.05)

    success = db.update_interaction_status(record_id, InteractionStatus.MERGED)
    assert success is True

    after = db.get_interaction(
        "https://github.com/owner/repo", "https://example.com/broken"
    )
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

    record = db.get_interaction(
        "https://github.com/owner/repo", "https://example.com/broken"
    )
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
    assert db.is_blacklisted(
        "https://github.com/any/repo", maintainer="blocked_user"
    ) is True
    # Without specifying maintainer, repo itself is not blacklisted
    assert db.is_blacklisted("https://github.com/any/repo") is False
    # Different maintainer is fine
    assert db.is_blacklisted(
        "https://github.com/any/repo", maintainer="other_user"
    ) is False


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
        record = db.get_interaction(
            "https://github.com/owner/repo", "https://example.com/broken"
        )
        assert record is not None
        assert record.id == record_id
        assert record.status == InteractionStatus.SUBMITTED
        assert record.pr_url == "https://github.com/owner/repo/pull/1"
        assert record.maintainer == "alice"

        assert db.is_blacklisted(
            "https://github.com/any/repo", maintainer="blocked_user"
        ) is True

        assert db.has_been_submitted(
            "https://github.com/owner/repo", "https://example.com/broken"
        ) is True


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

    record = db.get_interaction(
        "https://github.com/owner/repo", "https://example.com/broken"
    )
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
    assert db.has_been_submitted(
        "https://github.com/owner/repo", "https://example.com/broken"
    ) is True


# ---------------------------------------------------------------------------
# Scenario 040 – Allow new URL (REQ-2)
# ---------------------------------------------------------------------------


def test_040_allow_new_url(db):
    """040: Allow new URL – False, no false positives (REQ-2)."""
    assert db.has_been_submitted(
        "https://github.com/owner/repo", "https://example.com/new"
    ) is False


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
    before = db.get_interaction(
        "https://github.com/owner/repo", "https://example.com/broken"
    )
    assert before is not None

    time.sleep(0.05)

    db.update_interaction_status(record_id, InteractionStatus.MERGED)
    after = db.get_interaction(
        "https://github.com/owner/repo", "https://example.com/broken"
    )
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
        assert db.has_been_submitted(
            "https://github.com/owner/repo", "https://example.com/broken"
        ) is True
        record = db.get_interaction(
            "https://github.com/owner/repo", "https://example.com/broken"
        )
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
    result = db.get_interaction(
        "https://github.com/nonexistent/repo", "https://example.com/nope"
    )
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
    record = db.get_interaction(
        "https://github.com/owner/repo", "https://example.com/broken"
    )
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
    record = db.get_interaction(
        "https://github.com/owner/repo", "https://example.com/broken"
    )
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
    assert db.is_blacklisted(
        "https://github.com/clean/repo", maintainer="blocked_user"
    ) is True

    # Clean repo + clean maintainer
    assert db.is_blacklisted(
        "https://github.com/clean/repo", maintainer="clean_user"
    ) is False
```



## Previous Attempt Failed (Attempt 2/3)

Your previous response had an error:

```
No code block found in response
```

Please fix this issue and provide the corrected, complete file contents.
IMPORTANT: Output the ENTIRE file, not just the fix.

## Output Format

Output ONLY the file contents. No explanations, no markdown headers, just the code.

```python
# Your implementation here
```

IMPORTANT:
- Output the COMPLETE file contents
- Do NOT output a summary or description
- Do NOT say "I've implemented..."
- Just output the code in a single code block
