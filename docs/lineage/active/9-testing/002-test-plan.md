# Extracted Test Plan

## Scenarios

### test_id
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Test Description | Expected Behavior | Status

### test_t010
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_check_url_success_head | Returns ok status for 200 response | RED

### test_t020
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_check_url_redirect | Returns ok status for 301/302 | RED

### test_t030
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_check_url_not_found | Returns error status for 404 | RED

### test_t040
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_check_url_server_error | Returns error status for 500 | RED

### test_t050
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_head_to_get_fallback_405 | Falls back to GET on 405 | RED

### test_t060
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_head_to_get_fallback_403 | Falls back to GET on 403 | RED

### test_t070
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_retry_on_429 | Retries with backoff on 429 | RED

### test_t080
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_retry_respects_retry_after | Uses Retry-After header value | RED

### test_t090
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_timeout_handling | Returns timeout status | RED

### test_t100
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_connection_reset | Returns disconnected status | RED

### test_t110
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_dns_failure | Returns failed status, no retry | RED

### test_t120
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_backoff_calculation | Correct exponential + jitter | RED

### test_t130
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_max_retries_honored | Stops after max_retries | RED

### test_t140
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_custom_user_agent | Sends configured User-Agent | RED

### test_t150
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_ssl_verification_configurable | Respects verify_ssl setting | RED

### test_010
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Successful HEAD request returns structured result (REQ-1) | Auto | URL returning 200 | status="ok", code=200 | Status and code match

### test_020
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Redirect response treated as success (REQ-1) | Auto | URL returning 301 | status="ok", code=301 | Redirects treated as success

### test_030
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Not found response returns error immediately (REQ-6) | Auto | URL returning 404 | status="error", code=404 | No retry attempted

### test_040
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Server error response categorized correctly (REQ-6) | Auto | URL returning 500 | status="error", code=500 | Correct status

### test_050
- Type: unit
- Requirement: 
- Mock needed: False
- Description: HEAD blocked 405 triggers GET fallback (REQ-3) | Auto | URL returning 405 then 200 on GET | status="ok", method="GET" | Fallback to GET works

### test_060
- Type: unit
- Requirement: 
- Mock needed: False
- Description: HEAD blocked 403 triggers GET fallback (REQ-3) | Auto | URL returning 403 then 200 on GET | status="ok", method="GET" | Fallback to GET works

### test_070
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Rate limited 429 triggers exponential backoff retry (REQ-2) | Auto | URL returning 429 twice then 200 | status="ok", retries=2 | Backoff applied

### test_080
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Retry-After header honored on 429 response (REQ-4) | Auto | 429 with Retry-After: 5 | Delay ≥ 5 seconds | Header respected

### test_090
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Request timeout returns timeout status (REQ-6) | Auto | Simulated timeout | status="timeout" | Timeout detected

### test_100
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Connection reset returns disconnected status (REQ-6) | Auto | RemoteDisconnected exception | status="disconnected" | Exception handled

### test_110
- Type: unit
- Requirement: 
- Mock needed: False
- Description: DNS failure returns failed status without retry (REQ-6) | Auto | URLError with DNS reason | status="failed", retries=0 | No retry on DNS

### test_120
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Backoff calculation uses exponential with jitter (REQ-2) | Auto | attempt=2, base=1.0 | delay in [4.0, 5.0] | Exponential + jitter

### test_130
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Max retries limit enforced (REQ-2) | Auto | Always 429 | retries=2, status="error" | Stops at max

### test_140
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Custom User-Agent configuration applied (REQ-5) | Auto | Custom UA string | Header contains custom value | UA sent correctly

### test_150
- Type: unit
- Requirement: 
- Mock needed: False
- Description: SSL verification configuration respected (REQ-5) | Auto | verify_ssl=False | No SSL errors | Context configured

### test_160
- Type: unit
- Requirement: 
- Mock needed: True
- Description: Module uses only stdlib dependencies (REQ-7) | Auto | Import check | No external imports | Only stdlib used

