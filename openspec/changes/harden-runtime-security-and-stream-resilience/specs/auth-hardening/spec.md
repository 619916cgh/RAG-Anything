## ADDED Requirements

### Requirement: Established WebSocket connections revalidate revocation
All WebSocket endpoints SHALL revalidate token revocation identity as well as account lifecycle and session generation before receiving client data or delivering protected events.

#### Scenario: Revocation after acceptance
- **WHEN** a previously accepted WebSocket token is revoked
- **THEN** the server closes the connection with code `4001` before its next protected receive or delivery
