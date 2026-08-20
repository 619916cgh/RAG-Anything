## 1. Authorization and KB Runtime

- [x] 1.1 Replace KB ownership/grant visibility and operate guards with
  existence plus the relevant global role permission; update duplicate list,
  switch, stats, and download checks.
- [x] 1.2 Make KB capabilities and rename/delete routes depend only on
  `kb:write`, `kb:manage`, and `kb:delete`; preserve owner fields as
  attribution only.
- [x] 1.3 Remove grant projection and member repository/runtime APIs while
  retaining historical grant migrations and table data untouched.

## 2. Shared Agents and Private Conversations

- [x] 2.1 Return all agents to `agent:read` callers and remove owner scope from
  agent create, update, delete, and use paths while retaining role permissions.
- [x] 2.2 Keep agent activity requester-local and enforce exact conversation
  ownership for every conversation, message, and streaming `thread_id` path,
  without a super-admin bypass.

## 3. Frontend and Public Interfaces

- [x] 3.1 Remove KB member drawer, editor capability/tab, and API-client
  operations; keep display-name editing for `kb:manage` users.
- [x] 3.2 Remove grant scope from client-facing auth/user representations and
  verify agent and KB pages use the new global resource lists.

## 4. Verification and Record

- [x] 4.1 Update backend role-matrix, grant-retirement, agent-sharing, and
  conversation-isolation tests, including cross-user streaming attempts.
- [x] 4.2 Update frontend unit/source-contract tests and run focused backend and
  frontend suites, OpenSpec strict validation, and diff checks.
- [x] 4.3 Record the completed behavior and verification boundary in
  `PROJECT_SUMMARY.md` without overwriting concurrent entries.
