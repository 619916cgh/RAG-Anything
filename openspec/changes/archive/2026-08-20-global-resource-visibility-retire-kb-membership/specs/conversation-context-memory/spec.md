## MODIFIED Requirements

### Requirement: 浼氳瘽鐢ㄦ埛闅旂

The system SHALL ensure that every agent conversation is accessible only to the
user recorded as its owner. This rule SHALL apply to list, get, create against
a shared agent, title update, deletion, message editing, history loading, and
streaming queries with a supplied `thread_id`; super-admins SHALL NOT bypass
the rule. Ownerless legacy threads MUST NOT be exposed through normal APIs.

#### Scenario: Shared agent keeps conversations private
- **WHEN** users A and B each create a conversation with the same shared agent
- **THEN** each user SHALL list and read only their own conversation

#### Scenario: Cross-user thread identifier is rejected
- **WHEN** user A supplies user B's `thread_id` to an agent conversation or
  streaming query endpoint
- **THEN** the system SHALL reject the request without reading or appending any
  of user B's messages

#### Scenario: Super-admin cannot inspect another user's conversation
- **WHEN** a super-admin targets a conversation owned by another user
- **THEN** the system SHALL reject the request without exposing conversation data
