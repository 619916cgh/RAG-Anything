## 1. Share persistence and administration

- [x] 1.1 Add the immutable PostgreSQL migration and manifest entry for demo shares and their rate/concurrency state.
- [x] 1.2 Add a repository/service for hashed-token share creation, lookup, revocation, rate limiting and concurrency leases.
- [x] 1.3 Add super-admin-only management endpoints and client helpers without returning stored token hashes.

## 2. Public cloud query and media boundaries

- [ ] 2.1 Extract or introduce a shared query execution path that preserves authenticated behavior and provides a non-persistent demo mode.
- [x] 2.2 Add anonymous bootstrap and SSE query endpoints that derive fixed agent/KB configuration from a valid share.
- [x] 2.3 Add short-lived, share-scoped media grants and a protected preview endpoint without exposing storage paths.

## 3. Demo interface

- [x] 3.1 Add public demo API/SSE utilities that keep fragment secrets out of URLs, storage and authorization headers.
- [x] 3.2 Add the kiosk `/demo/:shareId` route with streaming answers, citations, controlled media, cancellation and clear-in-memory behavior.
- [x] 3.3 Add super-admin share management controls and responsive demo styling outside the authenticated application shell.

## 4. Verification and handoff

- [x] 4.1 Add focused backend tests for share authorization, fixed scope, limits, revocation, non-persistence and media grants.
- [x] 4.2 Add frontend utility/source-contract tests for fragment parsing, SSE handling, safe API use and public route isolation.
- [ ] 4.3 Run focused tests, static checks, OpenSpec strict validation and scoped diff checks; document cloud-only acceptance steps.
- [x] 4.4 Update `PROJECT_SUMMARY.md` with implementation evidence and remaining cloud deployment acceptance.
