## MODIFIED Requirements

### Requirement: KB access enforces role-derived read and explicit write scope
All knowledge-base-scoped read endpoints SHALL allow a caller when the caller is `super_admin`, `dept_admin`, or `teacher`, owns the KB (`owner_id == current_user["id"]`), or has an explicit persisted grant for that KB. Role-derived visibility SHALL not create or alter an explicit grant. Write, management, and deletion endpoints SHALL retain their existing endpoint permission and object-scope rules; role-derived read visibility SHALL NOT bypass those rules. Any other request MUST return 403 Forbidden and MUST NOT return cross-owner KB data.

#### Scenario: Granted reader accesses another user's KB
- **WHEN** a user with `kb:read` and an explicit grant sends a request targeting another user's KB
- **THEN** the system SHALL allow the KB-scoped read request

#### Scenario: Granted student cannot write another user's KB
- **WHEN** a student with an explicit grant sends a KB write request targeting another user's KB
- **THEN** the system SHALL return 403 because the grant does not supply `kb:write`

#### Scenario: Role-derived reader accesses another user's KB
- **WHEN** a `dept_admin` or `teacher` without an explicit grant sends a read request targeting another user's KB
- **THEN** the system SHALL allow the read request without creating a grant row

#### Scenario: Assistant or student lacks cross-owner visibility
- **WHEN** an `assistant` or `student` without an explicit grant sends a request targeting another user's KB
- **THEN** the system SHALL return 403 without returning data from that KB

#### Scenario: Owner and super-admin access remain available
- **WHEN** the KB owner or a super-admin targets an existing KB
- **THEN** the system SHALL allow access subject to the endpoint's existing permission requirements

### Requirement: KB list endpoint projects effective per-KB capabilities
The `/api/kb/list` endpoint SHALL return all KBs to `super_admin`, `dept_admin`, and `teacher`. It SHALL return only owned and explicitly granted KBs to `assistant` and `student`. Each returned KB SHALL include effective `read`, `operate`, `rename`, `manage_members`, and `delete` capabilities. A role-derived readable KB SHALL report no write, member-management, rename, or delete capability unless separately authorized by the existing object-scope rules.

#### Scenario: Default-visible role lists another user's KB
- **WHEN** a `dept_admin` or `teacher` requests `GET /api/kb/list` without an explicit grant to another user's KB
- **THEN** the response SHALL include the KB with `read=true` and `operate=false`

#### Scenario: Revoked KB disappears for scope-limited roles
- **WHEN** an administrator revokes an `assistant` or `student` non-owner's access to a KB
- **THEN** the next authenticated `GET /api/kb/list` response SHALL not include that KB unless the user owns it
