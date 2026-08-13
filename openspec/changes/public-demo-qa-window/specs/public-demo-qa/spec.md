## ADDED Requirements

### Requirement: Super administrators manage public demo shares
The system SHALL allow only `super_admin` users to create, list, and revoke public demo shares. Each share MUST bind exactly one existing agent and that agent's configured knowledge base, and creation MUST reject an agent without a bound KB.

#### Scenario: Super administrator creates a share
- **WHEN** a super administrator creates a share for an existing agent with a bound KB
- **THEN** the system persists only a cryptographic hash of a newly generated secret and returns the raw secret exactly once

#### Scenario: Non-super administrator attempts share management
- **WHEN** a user without the `super_admin` role calls a demo-share management endpoint
- **THEN** the system returns 403 and creates, reveals, or revokes no share

### Requirement: Public demo requests are constrained by their share
The system SHALL accept an anonymous demo request only when its share ID and secret validate, the share is not revoked, and its rate and concurrency limits permit execution. The request MUST use the share's fixed agent and KB and MUST NOT accept client overrides for agent, KB, parser, model, retrieval settings, or user image input.

#### Scenario: Valid share streams a fixed-agent answer
- **WHEN** a visitor submits valid text through a non-revoked share within its limits
- **THEN** the system streams the answer using the share's configured agent and KB

#### Scenario: Revoked or invalid share is rejected
- **WHEN** a visitor submits a request with an invalid secret or revoked share
- **THEN** the system returns an authorization failure without revealing the agent or KB

#### Scenario: Share exceeds a limit
- **WHEN** a share exceeds its configured request-rate or concurrent-query limit
- **THEN** the system returns 429 and starts no retrieval

### Requirement: Public demo conversations are non-persistent
The system SHALL execute public demo questions without creating or updating agent conversations, agent messages, or conversation summaries.

#### Scenario: Visitor completes a demo question
- **WHEN** a public demo stream completes, fails, or is cancelled
- **THEN** no visitor question or answer exists in persistent conversation storage

### Requirement: Public media access remains share-scoped
The system SHALL expose public media only through a share-authenticated endpoint that verifies the share's fixed KB and a media ID. It MUST NOT disclose a filesystem path, permanent media URL, or ordinary authenticated download URL.

#### Scenario: Share previews its cited media
- **WHEN** a valid share requests a media ID returned for its fixed KB
- **THEN** the system returns a time-limited controlled preview response

#### Scenario: Share attempts cross-KB media access
- **WHEN** a valid share requests a media ID not belonging to its fixed KB
- **THEN** the system returns 404 or 403 without disclosing media metadata

