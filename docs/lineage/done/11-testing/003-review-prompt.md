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

# Test Plan for Issue #11

## Requirements to Cover

- REQ-1: A `setup_logging()` function exists that configures both file and console handlers
- REQ-2: Log files are written to a `logs/` directory with rotation enabled
- REQ-3: Console output uses stderr and includes timestamp, level, and message
- REQ-4: `check_links.py` uses the new logging system instead of print statements
- REQ-5: Log levels are configurable (default: INFO)
- REQ-6: Existing functionality of `check_links.py` is preserved

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
- **Description:** test_setup_logging_returns_logger | Returns configured Logger instance with both handlers | RED
- **Mock needed:** False
- **Assertions:** 

### test_t020
- **Type:** unit
- **Requirement:** 
- **Description:** test_log_directory_created | logs/ directory created if missing with rotation | RED
- **Mock needed:** False
- **Assertions:** 

### test_t030
- **Type:** unit
- **Requirement:** 
- **Description:** test_console_output_format | Console output uses stderr with timestamp, level, message | RED
- **Mock needed:** False
- **Assertions:** 

### test_t040
- **Type:** unit
- **Requirement:** 
- **Description:** test_check_links_uses_logging | check_links.py logs instead of prints | RED
- **Mock needed:** False
- **Assertions:** 

### test_t050
- **Type:** unit
- **Requirement:** 
- **Description:** test_log_level_configurable | Logger level matches parameter (default: INFO) | RED
- **Mock needed:** False
- **Assertions:** 

### test_t060
- **Type:** unit
- **Requirement:** 
- **Description:** test_existing_functionality_preserved | check_links.py still finds and checks URLs correctly | RED
- **Mock needed:** False
- **Assertions:** 

### test_010
- **Type:** unit
- **Requirement:** 
- **Description:** setup_logging creates logger with both handlers (REQ-1) | Auto | name="test", console=True, file=True | Logger with StreamHandler and RotatingFileHandler | len(handlers) == 2 and correct types
- **Mock needed:** False
- **Assertions:** 

### test_020
- **Type:** unit
- **Requirement:** 
- **Description:** Log directory created with rotation enabled (REQ-2) | Auto | log_dir="test_logs", file=True | Directory exists, RotatingFileHandler configured | Path exists and handler.maxBytes > 0
- **Mock needed:** False
- **Assertions:** 

### test_030
- **Type:** unit
- **Requirement:** 
- **Description:** Console output format includes timestamp, level, message (REQ-3) | Auto | Log INFO message | Output on stderr with ISO timestamp, level, message | Regex matches expected format
- **Mock needed:** False
- **Assertions:** 

### test_040
- **Type:** unit
- **Requirement:** 
- **Description:** check_links uses logging instead of print (REQ-4) | Auto | Run find_urls | No stdout/print output, log records captured | caplog has records, stdout empty
- **Mock needed:** False
- **Assertions:** 

### test_050
- **Type:** unit
- **Requirement:** 
- **Description:** Log levels are configurable with INFO default (REQ-5) | Auto | level="DEBUG" vs default | Logger.level matches param | logger.level == logging.DEBUG; default == INFO
- **Mock needed:** False
- **Assertions:** 

### test_060
- **Type:** unit
- **Requirement:** 
- **Description:** check_links existing functionality preserved (REQ-6) | Auto | Run check_url on test URL | Returns status string, same behavior | Status string format unchanged
- **Mock needed:** False
- **Assertions:** 

## Original Test Plan Section

*Ref: [0005-testing-strategy-and-protocols.md](0005-testing-strategy-and-protocols.md)*

**Testing Philosophy:** Strive for 100% automated test coverage. Manual tests are a last resort for scenarios that genuinely cannot be automated.

### 10.0 Test Plan (TDD - Complete Before Implementation)

**TDD Requirement:** Tests MUST be written and failing BEFORE implementation begins.

| Test ID | Test Description | Expected Behavior | Status |
|---------|------------------|-------------------|--------|
| T010 | test_setup_logging_returns_logger | Returns configured Logger instance with both handlers | RED |
| T020 | test_log_directory_created | logs/ directory created if missing with rotation | RED |
| T030 | test_console_output_format | Console output uses stderr with timestamp, level, message | RED |
| T040 | test_check_links_uses_logging | check_links.py logs instead of prints | RED |
| T050 | test_log_level_configurable | Logger level matches parameter (default: INFO) | RED |
| T060 | test_existing_functionality_preserved | check_links.py still finds and checks URLs correctly | RED |

**Coverage Target:** ≥95% for all new code

**TDD Checklist:**
- [ ] All tests written before implementation
- [ ] Tests currently RED (failing)
- [ ] Test IDs match scenario IDs in 10.1
- [ ] Test file created at: `tests/unit/test_logging_config.py`

### 10.1 Test Scenarios

| ID | Scenario | Type | Input | Expected Output | Pass Criteria |
|----|----------|------|-------|-----------------|---------------|
| 010 | setup_logging creates logger with both handlers (REQ-1) | Auto | name="test", console=True, file=True | Logger with StreamHandler and RotatingFileHandler | len(handlers) == 2 and correct types |
| 020 | Log directory created with rotation enabled (REQ-2) | Auto | log_dir="test_logs", file=True | Directory exists, RotatingFileHandler configured | Path exists and handler.maxBytes > 0 |
| 030 | Console output format includes timestamp, level, message (REQ-3) | Auto | Log INFO message | Output on stderr with ISO timestamp, level, message | Regex matches expected format |
| 040 | check_links uses logging instead of print (REQ-4) | Auto | Run find_urls | No stdout/print output, log records captured | caplog has records, stdout empty |
| 050 | Log levels are configurable with INFO default (REQ-5) | Auto | level="DEBUG" vs default | Logger.level matches param | logger.level == logging.DEBUG; default == INFO |
| 060 | check_links existing functionality preserved (REQ-6) | Auto | Run check_url on test URL | Returns status string, same behavior | Status string format unchanged |

### 10.2 Test Commands

```bash
# Run all automated tests
poetry run pytest tests/unit/test_logging_config.py -v

# Run with coverage
poetry run pytest tests/unit/test_logging_config.py -v --cov=src/logging_config --cov-report=term-missing

# Run integration test for check_links
poetry run pytest tests/unit/test_logging_config.py::test_check_links_uses_logging -v
```

### 10.3 Manual Tests (Only If Unavoidable)

N/A - All scenarios automated.
