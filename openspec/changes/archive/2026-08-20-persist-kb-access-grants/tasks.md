## 1. Persistent Scope

- [x] 1.1 Add the additive `kb_access_grants` migration and append it to the reviewed manifest.
- [x] 1.2 Add transactional PostgreSQL grant read/replace helpers with target and KB validation.

## 2. Authorization Projection

- [x] 2.1 Project grants in sanitized authenticated users and invalidate the target session after a grant change.
- [x] 2.2 Apply owner-or-grant scope consistently to KB access and KB listing without bypassing role permissions.
- [x] 2.3 Add role-derived all-KB read visibility for super_admin, dept_admin, and teacher without changing explicit grants or write/manage/delete scope.

## 3. Administrator Experience

- [x] 3.1 Extend the authorized user editor with accessible KB grant selection and save/reset states.
- [x] 3.2 Preserve five-role navigation and KB-page write gates after a scope grant or revocation.
- [x] 3.3 Project per-KB read/operate/manage/delete capabilities and hide mutation controls for role-derived read-only KBs.

## 4. Verification

- [x] 4.1 Superseded by `global-resource-visibility-retire-kb-membership`: add backend regression coverage for global KB visibility, role-derived capabilities, permission denial, session-generation invalidation, and retired `allowed_kbs` rejection; do not restore persistent grant runtime behavior.
- [x] 4.2 Superseded by `global-resource-visibility-retire-kb-membership`: add frontend coverage for five-role capability gating, confirmed KB membership, `users:write` user editing, and the absence of retired grant controls.
- [x] 4.3 Repair the migration-runner applied-status display for empty failure diagnostics and cover it with a regression test.
- [x] 4.4 Run targeted tests, OpenSpec strict validation, diff checks, migration status, and authenticated PostgreSQL/browser acceptance. Code-level and isolated PostgreSQL fresh/verify/repeat/auth/backfill checks passed. A clean detached candidate with a revision-labeled image completed five-role browser list/detail/capability and user-editor acceptance against an isolated PostgreSQL stack; Worker and production acceptance remain out of scope and unexecuted.

## 5. Project Record

- [x] 5.1 Update `PROJECT_SUMMARY.md` with persisted-grant behavior, migration evidence, validation results, and any remaining runtime limitation.
