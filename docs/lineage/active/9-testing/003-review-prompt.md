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

# Test Plan for Issue #9

## Requirements to Cover

- REQ-1: Module provides `check_url()` function that returns structured results matching 00008 schema
- REQ-2: Implements exponential backoff with jitter per standard 00007
- REQ-3: Supports HEAD→GET fallback for 403/405 responses
- REQ-4: Respects Retry-After headers on 429 responses
- REQ-5: Allows configurable timeout, SSL verification, and User-Agent
- REQ-6: Correctly categorizes all response types (ok, error, timeout, failed, disconnected, invalid)
- REQ-7: No external dependencies beyond Python standard library

## Detected Test Types

- browser
- e2e
- integration
- mobile
- performance
- security
- terminal
- unit

## Required Tools

- appium
- bandit
- click.testing
- detox
- docker-compose
- locust
- pexpect
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
**Terminal/CLI Tests:** Use CliRunner or capture stdout/stderr
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
- **Description:** test_check_url_success_head | Returns ok status for 200 response | RED
- **Mock needed:** False
- **Assertions:** 

### test_t020
- **Type:** unit
- **Requirement:** 
- **Description:** test_check_url_redirect | Returns ok status for 301/302 | RED
- **Mock needed:** False
- **Assertions:** 

### test_t030
- **Type:** unit
- **Requirement:** 
- **Description:** test_check_url_not_found | Returns error status for 404 | RED
- **Mock needed:** False
- **Assertions:** 

### test_t040
- **Type:** unit
- **Requirement:** 
- **Description:** test_check_url_server_error | Returns error status for 500 | RED
- **Mock needed:** False
- **Assertions:** 

### test_t050
- **Type:** unit
- **Requirement:** 
- **Description:** test_head_to_get_fallback_405 | Falls back to GET on 405 | RED
- **Mock needed:** False
- **Assertions:** 

### test_t060
- **Type:** unit
- **Requirement:** 
- **Description:** test_head_to_get_fallback_403 | Falls back to GET on 403 | RED
- **Mock needed:** False
- **Assertions:** 

### test_t070
- **Type:** unit
- **Requirement:** 
- **Description:** test_retry_on_429 | Retries with backoff on 429 | RED
- **Mock needed:** False
- **Assertions:** 

### test_t080
- **Type:** unit
- **Requirement:** 
- **Description:** test_retry_respects_retry_after | Uses Retry-After header value | RED
- **Mock needed:** False
- **Assertions:** 

### test_t090
- **Type:** unit
- **Requirement:** 
- **Description:** test_timeout_handling | Returns timeout status | RED
- **Mock needed:** False
- **Assertions:** 

### test_t100
- **Type:** unit
- **Requirement:** 
- **Description:** test_connection_reset | Returns disconnected status | RED
- **Mock needed:** False
- **Assertions:** 

### test_t110
- **Type:** unit
- **Requirement:** 
- **Description:** test_dns_failure | Returns failed status, no retry | RED
- **Mock needed:** False
- **Assertions:** 

### test_t120
- **Type:** unit
- **Requirement:** 
- **Description:** test_backoff_calculation | Correct exponential + jitter | RED
- **Mock needed:** False
- **Assertions:** 

### test_t130
- **Type:** unit
- **Requirement:** 
- **Description:** test_max_retries_honored | Stops after max_retries | RED
- **Mock needed:** False
- **Assertions:** 

### test_t140
- **Type:** unit
- **Requirement:** 
- **Description:** test_custom_user_agent | Sends configured User-Agent | RED
- **Mock needed:** False
- **Assertions:** 

### test_t150
- **Type:** unit
- **Requirement:** 
- **Description:** test_ssl_verification_configurable | Respects verify_ssl setting | RED
- **Mock needed:** False
- **Assertions:** 

### test_010
- **Type:** unit
- **Requirement:** 
- **Description:** Successful HEAD request returns structured result (REQ-1) | Auto | URL returning 200 | status="ok", code=200 | Status and code match
- **Mock needed:** False
- **Assertions:** 

### test_020
- **Type:** unit
- **Requirement:** 
- **Description:** Redirect response treated as success (REQ-1) | Auto | URL returning 301 | status="ok", code=301 | Redirects treated as success
- **Mock needed:** False
- **Assertions:** 

### test_030
- **Type:** unit
- **Requirement:** 
- **Description:** Not found response returns error immediately (REQ-6) | Auto | URL returning 404 | status="error", code=404 | No retry attempted
- **Mock needed:** False
- **Assertions:** 

### test_040
- **Type:** unit
- **Requirement:** 
- **Description:** Server error response categorized correctly (REQ-6) | Auto | URL returning 500 | status="error", code=500 | Correct status
- **Mock needed:** False
- **Assertions:** 

### test_050
- **Type:** unit
- **Requirement:** 
- **Description:** HEAD blocked 405 triggers GET fallback (REQ-3) | Auto | URL returning 405 then 200 on GET | status="ok", method="GET" | Fallback to GET works
- **Mock needed:** False
- **Assertions:** 

### test_060
- **Type:** unit
- **Requirement:** 
- **Description:** HEAD blocked 403 triggers GET fallback (REQ-3) | Auto | URL returning 403 then 200 on GET | status="ok", method="GET" | Fallback to GET works
- **Mock needed:** False
- **Assertions:** 

### test_070
- **Type:** unit
- **Requirement:** 
- **Description:** Rate limited 429 triggers exponential backoff retry (REQ-2) | Auto | URL returning 429 twice then 200 | status="ok", retries=2 | Backoff applied
- **Mock needed:** False
- **Assertions:** 

### test_080
- **Type:** unit
- **Requirement:** 
- **Description:** Retry-After header honored on 429 response (REQ-4) | Auto | 429 with Retry-After: 5 | Delay ≥ 5 seconds | Header respected
- **Mock needed:** False
- **Assertions:** 

### test_090
- **Type:** unit
- **Requirement:** 
- **Description:** Request timeout returns timeout status (REQ-6) | Auto | Simulated timeout | status="timeout" | Timeout detected
- **Mock needed:** False
- **Assertions:** 

### test_100
- **Type:** unit
- **Requirement:** 
- **Description:** Connection reset returns disconnected status (REQ-6) | Auto | RemoteDisconnected exception | status="disconnected" | Exception handled
- **Mock needed:** False
- **Assertions:** 

### test_110
- **Type:** unit
- **Requirement:** 
- **Description:** DNS failure returns failed status without retry (REQ-6) | Auto | URLError with DNS reason | status="failed", retries=0 | No retry on DNS
- **Mock needed:** False
- **Assertions:** 

### test_120
- **Type:** unit
- **Requirement:** 
- **Description:** Backoff calculation uses exponential with jitter (REQ-2) | Auto | attempt=2, base=1.0 | delay in [4.0, 5.0] | Exponential + jitter
- **Mock needed:** False
- **Assertions:** 

### test_130
- **Type:** unit
- **Requirement:** 
- **Description:** Max retries limit enforced (REQ-2) | Auto | Always 429 | retries=2, status="error" | Stops at max
- **Mock needed:** False
- **Assertions:** 

### test_140
- **Type:** unit
- **Requirement:** 
- **Description:** Custom User-Agent configuration applied (REQ-5) | Auto | Custom UA string | Header contains custom value | UA sent correctly
- **Mock needed:** False
- **Assertions:** 

### test_150
- **Type:** unit
- **Requirement:** 
- **Description:** SSL verification configuration respected (REQ-5) | Auto | verify_ssl=False | No SSL errors | Context configured
- **Mock needed:** False
- **Assertions:** 

### test_160
- **Type:** unit
- **Requirement:** 
- **Description:** Module uses only stdlib dependencies (REQ-7) | Auto | Import check | No external imports | Only stdlib used
- **Mock needed:** True
- **Assertions:** 

## Original Test Plan Section

*Ref: [0005-testing-strategy-and-protocols.md](0005-testing-strategy-and-protocols.md)*

**Testing Philosophy:** 100% automated test coverage for all network module logic using mocked HTTP responses.

### 10.0 Test Plan (TDD - Complete Before Implementation)

**TDD Requirement:** Tests MUST be written and failing BEFORE implementation begins.

| Test ID | Test Description | Expected Behavior | Status |
|---------|------------------|-------------------|--------|
| T010 | test_check_url_success_head | Returns ok status for 200 response | RED |
| T020 | test_check_url_redirect | Returns ok status for 301/302 | RED |
| T030 | test_check_url_not_found | Returns error status for 404 | RED |
| T040 | test_check_url_server_error | Returns error status for 500 | RED |
| T050 | test_head_to_get_fallback_405 | Falls back to GET on 405 | RED |
| T060 | test_head_to_get_fallback_403 | Falls back to GET on 403 | RED |
| T070 | test_retry_on_429 | Retries with backoff on 429 | RED |
| T080 | test_retry_respects_retry_after | Uses Retry-After header value | RED |
| T090 | test_timeout_handling | Returns timeout status | RED |
| T100 | test_connection_reset | Returns disconnected status | RED |
| T110 | test_dns_failure | Returns failed status, no retry | RED |
| T120 | test_backoff_calculation | Correct exponential + jitter | RED |
| T130 | test_max_retries_honored | Stops after max_retries | RED |
| T140 | test_custom_user_agent | Sends configured User-Agent | RED |
| T150 | test_ssl_verification_configurable | Respects verify_ssl setting | RED |

**Coverage Target:** ≥95% for all new code

**TDD Checklist:**
- [ ] All tests written before implementation
- [ ] Tests currently RED (failing)
- [ ] Test IDs match scenario IDs in 10.1
- [ ] Test file created at: `tests/unit/test_network.py`

### 10.1 Test Scenarios

| ID | Scenario | Type | Input | Expected Output | Pass Criteria |
|----|----------|------|-------|-----------------|---------------|
| 010 | Successful HEAD request returns structured result (REQ-1) | Auto | URL returning 200 | status="ok", code=200 | Status and code match |
| 020 | Redirect response treated as success (REQ-1) | Auto | URL returning 301 | status="ok", code=301 | Redirects treated as success |
| 030 | Not found response returns error immediately (REQ-6) | Auto | URL returning 404 | status="error", code=404 | No retry attempted |
| 040 | Server error response categorized correctly (REQ-6) | Auto | URL returning 500 | status="error", code=500 | Correct status |
| 050 | HEAD blocked 405 triggers GET fallback (REQ-3) | Auto | URL returning 405 then 200 on GET | status="ok", method="GET" | Fallback to GET works |
| 060 | HEAD blocked 403 triggers GET fallback (REQ-3) | Auto | URL returning 403 then 200 on GET | status="ok", method="GET" | Fallback to GET works |
| 070 | Rate limited 429 triggers exponential backoff retry (REQ-2) | Auto | URL returning 429 twice then 200 | status="ok", retries=2 | Backoff applied |
| 080 | Retry-After header honored on 429 response (REQ-4) | Auto | 429 with Retry-After: 5 | Delay ≥ 5 seconds | Header respected |
| 090 | Request timeout returns timeout status (REQ-6) | Auto | Simulated timeout | status="timeout" | Timeout detected |
| 100 | Connection reset returns disconnected status (REQ-6) | Auto | RemoteDisconnected exception | status="disconnected" | Exception handled |
| 110 | DNS failure returns failed status without retry (REQ-6) | Auto | URLError with DNS reason | status="failed", retries=0 | No retry on DNS |
| 120 | Backoff calculation uses exponential with jitter (REQ-2) | Auto | attempt=2, base=1.0 | delay in [4.0, 5.0] | Exponential + jitter |
| 130 | Max retries limit enforced (REQ-2) | Auto | Always 429 | retries=2, status="error" | Stops at max |
| 140 | Custom User-Agent configuration applied (REQ-5) | Auto | Custom UA string | Header contains custom value | UA sent correctly |
| 150 | SSL verification configuration respected (REQ-5) | Auto | verify_ssl=False | No SSL errors | Context configured |
| 160 | Module uses only stdlib dependencies (REQ-7) | Auto | Import check | No external imports | Only stdlib used |

### 10.2 Test Commands

```bash
# Run all automated tests
poetry run pytest tests/unit/test_network.py -v

# Run only fast/mocked tests (exclude live)
poetry run pytest tests/unit/test_network.py -v -m "not live"

# Run with coverage
poetry run pytest tests/unit/test_network.py -v --cov=src/gh_link_auditor/network --cov-report=term-missing
```

### 10.3 Manual Tests (Only If Unavoidable)

N/A - All scenarios automated using mocked HTTP responses.
