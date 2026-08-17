## MODIFIED Requirements

### Requirement: KB access enforces strict ownership isolation
All knowledge-base-scoped API endpoints SHALL allow an authenticated caller
with `kb:read` to access every existing knowledge base. Knowledge-base
ownership and persisted grants SHALL NOT restrict list, switch, read, download,
statistics, graph, or retrieval access. A caller without `kb:read` MUST receive
403 Forbidden and a nonexistent KB MUST return 404 Not Found.

#### Scenario: Student reads another creator's KB
- **WHEN** a student with `kb:read` requests a KB-scoped read endpoint for a KB
  created by another user
- **THEN** the request SHALL succeed and return data from the requested KB

#### Scenario: Caller lacks KB read permission
- **WHEN** an authenticated caller without `kb:read` targets an existing KB
- **THEN** the system SHALL return 403 Forbidden

#### Scenario: Unknown KB is requested
- **WHEN** a caller targets a KB that does not exist
- **THEN** the system SHALL return 404 Not Found

### Requirement: KB list endpoint filters by ownership
The `/api/kb/list` endpoint SHALL return every knowledge base to a caller with
`kb:read`. Returned capabilities SHALL be derived only from the caller's global
role permissions: content operation from `kb:write`, rename from `kb:manage`,
and deletion from `kb:delete`. Ownership and persisted grants SHALL NOT alter
those capabilities.

#### Scenario: New student lists existing KBs
- **WHEN** a newly created student with no owned KB and no historical grant
  requests `GET /api/kb/list`
- **THEN** the response SHALL contain every existing KB with read capability

#### Scenario: Assistant operates another creator's KB
- **WHEN** an assistant with `kb:write` inspects another user's KB in the list
- **THEN** its operation capability SHALL be true regardless of owner or grant

#### Scenario: Student has no KB mutation capability
- **WHEN** a student inspects any KB in the list
- **THEN** its operation, rename, and delete capabilities SHALL be false
