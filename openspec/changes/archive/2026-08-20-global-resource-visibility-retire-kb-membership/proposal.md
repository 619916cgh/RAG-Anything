## Why

New students currently receive `kb:read` and `agent:read` yet cannot see shared
resources because object ownership and per-KB grants add a second, hidden access
scope. This makes ordinary teaching use unnecessarily difficult and leaves agent
visibility inconsistent with knowledge-base visibility.

## What Changes

- Make every authenticated role with `kb:read` able to list, switch, read,
  download, retrieve from, and use every knowledge base.
- Make every authenticated role with `agent:read` able to list and use every
  agent. Resource creation, update, rename, and deletion remain controlled only
  by the existing role permissions.
- **BREAKING** Remove KB member-management UI and `/api/kb/{kb}/members*`
  endpoints. Existing grant rows and historical migrations remain intact but no
  longer affect runtime access.
- Remove grant scope from authentication and user payloads while continuing to
  reject legacy `allowed_kbs` update input explicitly.
- Keep agent conversations private to their creator, including from
  super-admins. A shared agent must not permit a supplied `thread_id` to expose
  or append to another user's conversation.

## Capabilities

### New Capabilities
- `global-agent-visibility`: all readable agents are discoverable and usable by
  every role, while management remains role-permission based.

### Modified Capabilities
- `kb-access-control`: replace ownership/grant-based KB visibility and mutation
  scope with global role-permission checks.
- `conversation-context-memory`: require conversation ownership on every agent
  conversation and stream path without an administrator bypass.
- `admin-user-crud`: retire grant scope from user representations and the
  member-management contract.

## Impact

Affected areas include FastAPI KB and agent routers, authorization dependencies,
PostgreSQL repositories, authentication responses, React KB and agent screens,
and role-matrix tests. No dependency or database migration is required; the
historical `kb_access_grants` table remains inert for audit and rollback.
