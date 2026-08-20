## ADDED Requirements

### Requirement: Sensitive account mutations honor target hierarchy
The system SHALL determine the actor and target roles from locked PostgreSQL rows in the same transaction before changing a username, password, active state, archive state, or role. An actor SHALL NOT mutate a target whose current role is more privileged than the actor's role.

#### Scenario: Department administrator targets a super administrator
- **WHEN** a `dept_admin` attempts to rename, reset the password of, disable, demote, or archive a `super_admin`
- **THEN** the repository and HTTP API reject the mutation with authorization failure

#### Scenario: Same-level administrator targets a peer
- **WHEN** a `dept_admin` mutates a peer `dept_admin` account
- **THEN** the mutation follows the existing lifecycle and final-super-admin protections
