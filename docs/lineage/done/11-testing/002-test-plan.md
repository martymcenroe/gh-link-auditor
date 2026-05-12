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
- Description: test_setup_logging_returns_logger | Returns configured Logger instance with both handlers | RED

### test_t020
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_log_directory_created | logs/ directory created if missing with rotation | RED

### test_t030
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_console_output_format | Console output uses stderr with timestamp, level, message | RED

### test_t040
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_check_links_uses_logging | check_links.py logs instead of prints | RED

### test_t050
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_log_level_configurable | Logger level matches parameter (default: INFO) | RED

### test_t060
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_existing_functionality_preserved | check_links.py still finds and checks URLs correctly | RED

### test_010
- Type: unit
- Requirement: 
- Mock needed: False
- Description: setup_logging creates logger with both handlers (REQ-1) | Auto | name="test", console=True, file=True | Logger with StreamHandler and RotatingFileHandler | len(handlers) == 2 and correct types

### test_020
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Log directory created with rotation enabled (REQ-2) | Auto | log_dir="test_logs", file=True | Directory exists, RotatingFileHandler configured | Path exists and handler.maxBytes > 0

### test_030
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Console output format includes timestamp, level, message (REQ-3) | Auto | Log INFO message | Output on stderr with ISO timestamp, level, message | Regex matches expected format

### test_040
- Type: unit
- Requirement: 
- Mock needed: False
- Description: check_links uses logging instead of print (REQ-4) | Auto | Run find_urls | No stdout/print output, log records captured | caplog has records, stdout empty

### test_050
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Log levels are configurable with INFO default (REQ-5) | Auto | level="DEBUG" vs default | Logger.level matches param | logger.level == logging.DEBUG; default == INFO

### test_060
- Type: unit
- Requirement: 
- Mock needed: False
- Description: check_links existing functionality preserved (REQ-6) | Auto | Run check_url on test URL | Returns status string, same behavior | Status string format unchanged

