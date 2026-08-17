## ADDED Requirements

### Requirement: Agent visibility and management follow global role permissions
The system SHALL return every agent to any authenticated caller with
`agent:read` and SHALL allow that caller to use any returned agent. Agent
creation and update SHALL require `agent:write`, and deletion SHALL require
`agent:delete`, without evaluating the agent creator as authorization scope.
Agent creator fields SHALL remain attribution only.

#### Scenario: Student uses another creator's agent
- **WHEN** a student with `agent:read` lists agents and starts a conversation
  with an agent created by another user
- **THEN** the list and conversation creation SHALL succeed

#### Scenario: Agent mutation uses role permission only
- **WHEN** a teacher with `agent:write` updates an agent created by another user
- **THEN** the update SHALL succeed without an ownership or grant check

#### Scenario: Student cannot mutate a shared agent
- **WHEN** a student without `agent:write` attempts to update any agent
- **THEN** the system SHALL return 403 Forbidden

### Requirement: Shared agent activity does not expose other users' conversations
The agent directory SHALL calculate conversation count and last activity for the
requesting user's own conversations only.

#### Scenario: Shared agent is viewed by two users
- **WHEN** two users each have conversations with the same agent
- **THEN** each user SHALL receive activity derived only from their own threads
