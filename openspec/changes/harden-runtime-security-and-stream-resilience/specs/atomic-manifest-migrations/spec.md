## ADDED Requirements

### Requirement: Manifest migrations serialize and record atomically
The runner SHALL acquire a stable PostgreSQL advisory transaction lock, recheck migration history while holding that lock, execute a transaction-compatible migration, record `applied` history, and commit in one `psql` session and transaction. A waiter that observes already-applied history SHALL no-op.

#### Scenario: Two runners apply the same pending migration
- **WHEN** two runners target the same pending migration concurrently
- **THEN** exactly one executes the SQL and the other completes without re-executing it

#### Scenario: Migration SQL fails
- **WHEN** migration SQL fails before commit
- **THEN** its SQL changes and applied history record are rolled back and a sanitized diagnostic failure record is written separately

### Requirement: Unsupported transactional migration syntax fails closed
The runner SHALL reject migration files with incompatible transaction boundaries or non-transactional DDL before executing them through the atomic path.

#### Scenario: Migration contains concurrent index creation
- **WHEN** a manifest migration contains `CREATE INDEX CONCURRENTLY`
- **THEN** the runner refuses the migration with an actionable, sanitized error

### Requirement: PostgreSQL URL options survive runner translation
The runner SHALL forward supported libpq TLS and connection options from `DATABASE_URL` without emitting their values in diagnostics.

#### Scenario: Private-CA connection URL
- **WHEN** `DATABASE_URL` contains encoded `sslrootcert`, `sslcert`, `sslkey`, and `connect_timeout` options
- **THEN** the generated psql environment retains the supported options and diagnostics do not contain the URL
