# Test Plan Review Prompt

You are reviewing a test plan extracted from a Low-Level Design (LLD) document.
Your goal is to ensure the test plan provides adequate coverage and uses real, executable tests.

## Review Criteria

### 1. Coverage Analysis (CRITICAL)
- [ ] 100% of requirements have corresponding tests (ADR 0207)
- [ ] Each requirement maps to at least one test scenario
- [ ] Edge cases are covered (empty inputs, error conditions, boundaries)

### 2. Test Reality Check (CRITICAL)
- [ ] Tests are executable code, not human manual steps
- [ ] No test delegates to "manual verification"
- [ ] No test says "verify by inspection" or similar
- [ ] Each test has clear assertions

### 3. Test Type Appropriateness
- [ ] Unit tests are truly isolated (mock dependencies)
- [ ] Integration tests test real component interactions
- [ ] E2E tests cover critical user paths

### 4. Mock Strategy
- [ ] External dependencies (APIs, DB) are mocked appropriately
- [ ] Mocks are realistic and don't hide bugs

## Output Format

Provide your verdict in this exact format:

```
## Coverage Analysis
- Requirements covered: X/Y (Z%)
- Missing coverage: [list any gaps]

## Test Reality Issues
- [list any tests that aren't real executable tests]

## Verdict
[x] **APPROVED** - Test plan is ready for implementation
OR
[x] **BLOCKED** - Test plan needs revision

## Required Changes (if BLOCKED)
1. [specific change needed]
2. [specific change needed]
```


---

# Test Plan for Issue #5

## Requirements to Cover

- REQ-1: Bot queries the database before EVERY submission attempt
- REQ-2: Duplicate submissions to the same (repo_url, broken_url) pair are prevented
- REQ-3: Blacklisted maintainers receive no bot contact regardless of repo
- REQ-4: Blacklisted repos receive no bot contact regardless of broken URL
- REQ-5: All interactions are logged with timestamps for audit trail
- REQ-6: Database persists across bot restarts
- REQ-7: Status transitions are tracked (submitted → merged/denied)

## Detected Test Types

- browser
- e2e
- integration
- mobile
- performance
- security
- unit

## Required Tools

- appium
- bandit
- detox
- docker-compose
- locust
- playwright
- pytest
- pytest-benchmark
- safety
- selenium

## Mock Guidance

**Browser/UI Tests:** Real browser required, mock backend APIs for isolation
**End-to-End Tests:** Minimal mocking - test against real (sandboxed) systems
**Integration Tests:** Use test doubles for external services, real DB where possible
**Mobile App Tests:** Use emulators/simulators, mock backend services
**Performance Tests:** Test against representative data volumes
**Security Tests:** Never use real credentials, test edge cases thoroughly
**Unit Tests:** Mock external dependencies (APIs, DB, filesystem)

## Coverage Target

95%

## Test Scenarios

### test_id
- **Type:** unit
- **Requirement:** 
- **Description:** Test Description | Expected Behavior | Status
- **Mock needed:** False
- **Assertions:** 

### test_t010
- **Type:** unit
- **Requirement:** 
- **Description:** test_create_database | Creates tables on init | RED
- **Mock needed:** True
- **Assertions:** 

### test_t020
- **Type:** unit
- **Requirement:** 
- **Description:** test_record_interaction | Stores interaction record | RED
- **Mock needed:** False
- **Assertions:** 

### test_t030
- **Type:** unit
- **Requirement:** 
- **Description:** test_has_been_submitted_true | Returns True for existing | RED
- **Mock needed:** False
- **Assertions:** 

### test_t040
- **Type:** unit
- **Requirement:** 
- **Description:** test_has_been_submitted_false | Returns False for new | RED
- **Mock needed:** False
- **Assertions:** 

### test_t050
- **Type:** unit
- **Requirement:** 
- **Description:** test_update_interaction_status | Updates status correctly | RED
- **Mock needed:** False
- **Assertions:** 

### test_t060
- **Type:** unit
- **Requirement:** 
- **Description:** test_add_to_blacklist | Adds blacklist entry | RED
- **Mock needed:** False
- **Assertions:** 

### test_t070
- **Type:** unit
- **Requirement:** 
- **Description:** test_is_blacklisted_repo | Detects blacklisted repo | RED
- **Mock needed:** False
- **Assertions:** 

### test_t080
- **Type:** unit
- **Requirement:** 
- **Description:** test_is_blacklisted_maintainer | Detects blacklisted maintainer | RED
- **Mock needed:** False
- **Assertions:** 

### test_t090
- **Type:** unit
- **Requirement:** 
- **Description:** test_can_submit_fix_ok | Returns True when allowed | RED
- **Mock needed:** False
- **Assertions:** 

### test_t100
- **Type:** unit
- **Requirement:** 
- **Description:** test_can_submit_fix_duplicate | Returns False for duplicate | RED
- **Mock needed:** False
- **Assertions:** 

### test_t110
- **Type:** unit
- **Requirement:** 
- **Description:** test_can_submit_fix_blacklisted | Returns False for blacklisted | RED
- **Mock needed:** False
- **Assertions:** 

### test_t120
- **Type:** unit
- **Requirement:** 
- **Description:** test_blacklist_expiration | Expired entries ignored | RED
- **Mock needed:** False
- **Assertions:** 

### test_t130
- **Type:** unit
- **Requirement:** 
- **Description:** test_get_stats | Returns correct counts | RED
- **Mock needed:** False
- **Assertions:** 

### test_t140
- **Type:** unit
- **Requirement:** 
- **Description:** test_database_persistence | Data persists across restarts | RED
- **Mock needed:** True
- **Assertions:** 

### test_010
- **Type:** unit
- **Requirement:** 
- **Description:** Create new database (REQ-1) | Auto | Empty path | Tables created | Schema matches spec
- **Mock needed:** True
- **Assertions:** 

### test_020
- **Type:** unit
- **Requirement:** 
- **Description:** Record new interaction (REQ-5) | Auto | Valid interaction data | Record ID returned | Record retrievable
- **Mock needed:** False
- **Assertions:** 

### test_030
- **Type:** unit
- **Requirement:** 
- **Description:** Detect submitted URL (REQ-2) | Auto | Existing repo+url | True | No false negatives
- **Mock needed:** False
- **Assertions:** 

### test_040
- **Type:** unit
- **Requirement:** 
- **Description:** Allow new URL (REQ-2) | Auto | New repo+url | False | No false positives
- **Mock needed:** False
- **Assertions:** 

### test_050
- **Type:** unit
- **Requirement:** 
- **Description:** Update status to merged (REQ-7) | Auto | Record ID + MERGED | Status updated | updated_at changed
- **Mock needed:** False
- **Assertions:** 

### test_060
- **Type:** unit
- **Requirement:** 
- **Description:** Add repo to blacklist (REQ-4) | Auto | Repo URL | Entry ID returned | is_blacklisted returns True
- **Mock needed:** False
- **Assertions:** 

### test_070
- **Type:** unit
- **Requirement:** 
- **Description:** Block blacklisted repo (REQ-4) | Auto | Blacklisted repo | can_submit_fix False | Reason includes "blacklisted"
- **Mock needed:** False
- **Assertions:** 

### test_080
- **Type:** unit
- **Requirement:** 
- **Description:** Block blacklisted maintainer (REQ-3) | Auto | Blacklisted maintainer | can_submit_fix False | Reason includes "blacklisted"
- **Mock needed:** False
- **Assertions:** 

### test_090
- **Type:** unit
- **Requirement:** 
- **Description:** Allow clean submission (REQ-1) | Auto | New repo, no blacklist | can_submit_fix True | Reason is "ok"
- **Mock needed:** False
- **Assertions:** 

### test_100
- **Type:** unit
- **Requirement:** 
- **Description:** Block duplicate submission (REQ-2) | Auto | Same repo+url twice | Second can_submit_fix False | Reason includes "already"
- **Mock needed:** False
- **Assertions:** 

### test_110
- **Type:** unit
- **Requirement:** 
- **Description:** Handle expired blacklist (REQ-4) | Auto | Expired entry | is_blacklisted False | Entry ignored
- **Mock needed:** False
- **Assertions:** 

### test_120
- **Type:** unit
- **Requirement:** 
- **Description:** Get statistics (REQ-5) | Auto | Populated DB | Correct counts | Matches manual count
- **Mock needed:** False
- **Assertions:** 

### test_130
- **Type:** integration
- **Requirement:** 
- **Description:** Close and reopen (REQ-6) | Integration | DB path | Data persisted | Records still present
- **Mock needed:** False
- **Assertions:** 

### test_140
- **Type:** unit
- **Requirement:** 
- **Description:** Query before submission (REQ-1) | Auto | Any submission attempt | DB queried first | Query logged/traced
- **Mock needed:** False
- **Assertions:** 

## Original Test Plan Section

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
