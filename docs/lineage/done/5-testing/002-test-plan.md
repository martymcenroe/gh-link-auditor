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
- Mock needed: True
- Description: test_create_database | Creates tables on init | RED

### test_t020
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_record_interaction | Stores interaction record | RED

### test_t030
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_has_been_submitted_true | Returns True for existing | RED

### test_t040
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_has_been_submitted_false | Returns False for new | RED

### test_t050
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_update_interaction_status | Updates status correctly | RED

### test_t060
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_add_to_blacklist | Adds blacklist entry | RED

### test_t070
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_is_blacklisted_repo | Detects blacklisted repo | RED

### test_t080
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_is_blacklisted_maintainer | Detects blacklisted maintainer | RED

### test_t090
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_can_submit_fix_ok | Returns True when allowed | RED

### test_t100
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_can_submit_fix_duplicate | Returns False for duplicate | RED

### test_t110
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_can_submit_fix_blacklisted | Returns False for blacklisted | RED

### test_t120
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_blacklist_expiration | Expired entries ignored | RED

### test_t130
- Type: unit
- Requirement: 
- Mock needed: False
- Description: test_get_stats | Returns correct counts | RED

### test_t140
- Type: unit
- Requirement: 
- Mock needed: True
- Description: test_database_persistence | Data persists across restarts | RED

### test_010
- Type: unit
- Requirement: 
- Mock needed: True
- Description: Create new database (REQ-1) | Auto | Empty path | Tables created | Schema matches spec

### test_020
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Record new interaction (REQ-5) | Auto | Valid interaction data | Record ID returned | Record retrievable

### test_030
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Detect submitted URL (REQ-2) | Auto | Existing repo+url | True | No false negatives

### test_040
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Allow new URL (REQ-2) | Auto | New repo+url | False | No false positives

### test_050
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Update status to merged (REQ-7) | Auto | Record ID + MERGED | Status updated | updated_at changed

### test_060
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Add repo to blacklist (REQ-4) | Auto | Repo URL | Entry ID returned | is_blacklisted returns True

### test_070
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Block blacklisted repo (REQ-4) | Auto | Blacklisted repo | can_submit_fix False | Reason includes "blacklisted"

### test_080
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Block blacklisted maintainer (REQ-3) | Auto | Blacklisted maintainer | can_submit_fix False | Reason includes "blacklisted"

### test_090
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Allow clean submission (REQ-1) | Auto | New repo, no blacklist | can_submit_fix True | Reason is "ok"

### test_100
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Block duplicate submission (REQ-2) | Auto | Same repo+url twice | Second can_submit_fix False | Reason includes "already"

### test_110
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Handle expired blacklist (REQ-4) | Auto | Expired entry | is_blacklisted False | Entry ignored

### test_120
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Get statistics (REQ-5) | Auto | Populated DB | Correct counts | Matches manual count

### test_130
- Type: integration
- Requirement: 
- Mock needed: False
- Description: Close and reopen (REQ-6) | Integration | DB path | Data persisted | Records still present

### test_140
- Type: unit
- Requirement: 
- Mock needed: False
- Description: Query before submission (REQ-1) | Auto | Any submission attempt | DB queried first | Query logged/traced

