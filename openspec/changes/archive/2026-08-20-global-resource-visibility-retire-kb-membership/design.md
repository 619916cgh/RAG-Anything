## Context

The current system combines global role permissions with object ownership and
`kb_access_grants`. That extra scope makes a new student unable to see any
existing KBs and makes non-owner agents invisible. The historical grant table
is already in the reviewed migration chain, so it must not be modified or
dropped as part of this behavior change.

## Goals / Non-Goals

**Goals:**

- Make KB and agent read/use scope global for authenticated roles with the
  respective read permission.
- Make management decisions depend only on the existing global permission
  matrix, not the resource owner or a membership grant.
- Remove member-management surfaces and prevent shared agents from weakening
  private conversation ownership.

**Non-Goals:**

- Do not change role definitions, delete historical grants, migrate resource
  ownership, or expose any user's conversation to another user.
- Do not change ingestion snapshots, KB identity, user settings, or demo-share
  authorization.

## Decisions

### 1. Separate immutable attribution from authorization

`owner_id` remains stored on KBs and agents for audit and presentation, but no
longer participates in read, mutation, or deletion authorization. KB read is
`kb:read`; content operations are `kb:write`; rename is `kb:manage`; deletion
is `kb:delete`. Agent discovery/use is `agent:read`, updates/creation are
`agent:write`, and deletion is `agent:delete`.

This keeps the existing five-role matrix intact while eliminating the hidden
per-resource rules. Replacing grants with a new shared role was rejected
because it would retain the complexity the change is meant to remove.

### 2. Retire membership at the runtime boundary without deleting its history

Remove grant projection from user records, all grant reads from access checks,
member repositories, routes, editor payloads, and frontend controls. Historical
tables, migrations, and rows remain inert. Deleting them would be a destructive
data migration with no product benefit and would make rollback/audit harder.

### 3. Share agents, not conversations

Agent listing returns all agents, while activity is calculated only for the
requesting user's conversations. Every conversation, message, and stream path
that accepts an existing `thread_id` validates exact `thread.owner_id ==
current_user.id`; there is no administrator override. Legacy ownerless threads
are not readable or writable through normal APIs.

### 4. Use one canonical authorization rule per operation class

The dependency helpers become the single object-existence and permission gate.
Duplicate list, switch, download, and route-local owner/grant checks are
removed. Existing endpoint-level permission dependencies are retained and each
mutation route is audited so making scope global cannot turn a read-only role
into a writer.

## Risks / Trade-offs

- [Existing integrations call member APIs] -> Remove the routes deliberately so
  callers receive 404 rather than a misleading no-op response.
- [A missed owner check preserves inconsistent behavior] -> Cover every route
  family with role-matrix and source-contract tests.
- [Shared agents leak conversations through `thread_id`] -> Validate ownership
  before loading history or writing messages, including in SSE paths.
- [Dormant grant rows are mistaken for active permissions] -> Remove grant
  fields from API responses and document the retention boundary in the summary.

## Migration Plan

1. Deploy application and frontend changes together; no database migration is
   run and `kb_access_grants` remains untouched.
2. Verify all five roles against API and browser read/use workflows, then verify
   role-only mutations and cross-user conversation denial.
3. Roll back application code to restore prior grant behavior if necessary;
   grant records remain available because this change never alters them.

## Open Questions

None.
