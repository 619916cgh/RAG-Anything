## ADDED Requirements

### Requirement: Release-candidate inventory is read-only
The system SHALL inventory tracked, staged, and untracked worktree paths and classify each as owned, shared, unowned, or generated-candidate based on active OpenSpec roots and protected shared assets. It SHALL not mutate Git state or filesystem content.

#### Scenario: Dirty worktree inventory
- **WHEN** an operator runs the inventory in a dirty worktree
- **THEN** it emits classifications and coordination warnings without staging, committing, resetting, checking out, deleting, or moving any path

#### Scenario: Shared release asset
- **WHEN** a changed path is `PROJECT_SUMMARY.md`, a migration manifest, a lockfile, or a deploy/Compose resource
- **THEN** the inventory SHALL classify it as shared and require serialized coordination
