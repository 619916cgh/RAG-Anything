## ADDED Requirements

### Requirement: User representations do not expose retired KB grant scope
Authentication and user-management responses SHALL NOT include `allowed_kbs` or
`kb_access_levels`. A user-update request containing legacy `allowed_kbs` MUST
be rejected explicitly rather than silently ignored.

#### Scenario: Authenticated user response is scope-free
- **WHEN** a user signs in or requests their current profile
- **THEN** the returned user representation SHALL not contain KB grant scope

#### Scenario: Legacy grant update is rejected
- **WHEN** an administrator submits `allowed_kbs` in a user update request
- **THEN** the system SHALL reject the request without modifying the user

### Requirement: KB member management interface is removed
The system SHALL NOT register KB member list, candidate search, grant, or
revoke endpoints, and KB editor responses SHALL NOT include member lists or
member-management capabilities.

#### Scenario: Legacy member endpoint is requested
- **WHEN** a caller requests a former `/api/kb/{kb}/members` path
- **THEN** the system SHALL return 404 Not Found
