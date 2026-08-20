## ADDED Requirements

### Requirement: Established WebSocket sessions remain revocable
The system SHALL retain the authenticated token JTI in each WebSocket session and SHALL fail closed before receiving or delivering events when the token is revoked, the account is inactive or archived, or the session generation has changed.

#### Scenario: Token revoked after connection
- **WHEN** a connected client's token is revoked
- **THEN** its next receive or server delivery closes the socket with code `4001` without sending an event

### Requirement: Ordinary task events are owner-directed
The system SHALL send ordinary upload and task events only to the matching `owner_user_id`. Events without an owner SHALL NOT be delivered to ordinary WebSocket clients, and raw exception text, paths, KB names, and filenames SHALL NOT be included in ordinary event payloads.

#### Scenario: Concurrent users receive task progress
- **WHEN** two authenticated users are connected and one user's task emits progress
- **THEN** only the task owner receives the projected progress event

### Requirement: Monitoring events require explicit authorization
The system SHALL expose aggregate monitor events only through a monitor-authorized connection surface and SHALL project each event to its documented non-sensitive fields.

#### Scenario: Non-monitor user requests monitoring stream
- **WHEN** a user without `monitor:read` connects to the monitor event surface
- **THEN** the connection is rejected before acceptance
