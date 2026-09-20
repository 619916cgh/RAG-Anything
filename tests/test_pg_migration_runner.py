import json
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.pg_migration_runner import (
    BackupAcknowledgementError,
    ChecksumDriftError,
    CommandResult,
    DatabaseStateError,
    ManifestError,
    MigrationApplyError,
    MigrationRunner,
    _load_project_dotenv,
    connection_environment,
    database_safe_failure,
    load_manifest,
    sanitize_failure,
    transaction_body_for_migration,
)


def test_project_dotenv_loads_without_overriding_environment(tmp_path):
    (tmp_path / ".env").write_text(
        "PGHOST=dotenv-host\nPGPORT=5439\n", encoding="utf-8"
    )
    with patch.dict(os.environ, {"PGHOST": "explicit-host"}, clear=False):
        os.environ.pop("PGPORT", None)
        _load_project_dotenv(tmp_path)
        assert os.environ["PGHOST"] == "explicit-host"
        assert os.environ["PGPORT"] == "5439"


class _FakePsql:
    def __init__(self, *, user_objects=0, fail_migration=None):
        self.history = {}
        self.user_objects = user_objects
        self.fail_migration = fail_migration
        self.calls = []
        self.executed_files = []

    def run(self, args, *, input_text=None):
        args = list(args)
        self.calls.append((args, input_text))
        if input_text is not None:
            match = re.search(
                r"VALUES\s*\('([^']+)',\s*(\d+),\s*'([0-9a-f]{64})',\s*'applied'",
                input_text,
                re.DOTALL,
            )
            assert match, input_text
            migration_id, sequence, checksum = match.groups()
            self.executed_files.append(migration_id)
            if migration_id == self.fail_migration:
                return CommandResult(3, "", "ERROR: relation pg_kb_meta does not exist")
            self.history[migration_id] = {
                "migration_id": migration_id,
                "sequence": int(sequence),
                "checksum": checksum,
                "state": "applied",
                "started_at": "2026-08-04T00:00:00+00:00",
                "completed_at": "2026-08-04T00:00:00+00:00",
                "failure_class": None,
                "failure_message": None,
            }
            return CommandResult(0)
        if "-f" in args:
            migration_id = Path(args[args.index("-f") + 1]).name
            self.executed_files.append(migration_id)
            if migration_id == self.fail_migration:
                return CommandResult(3, "", "ERROR: relation pg_kb_meta does not exist")
            return CommandResult(0)

        sql = args[args.index("-c") + 1] if "-c" in args else ""
        if "information_schema.tables" in sql:
            return CommandResult(0, f"{self.user_objects}\n")
        if "json_agg(row_to_json(history)" in sql:
            return CommandResult(0, json.dumps(list(self.history.values())) + "\n")
        if "INSERT INTO schema_migration_history" in sql:
            match = re.search(
                r"VALUES\s*\('([^']+)',\s*(\d+),\s*'([0-9a-f]{64})',\s*'(applied|failed)'",
                sql,
                re.DOTALL,
            )
            assert match, sql
            migration_id, sequence, checksum, state = match.groups()
            self.history[migration_id] = {
                "migration_id": migration_id,
                "sequence": int(sequence),
                "checksum": checksum,
                "state": state,
                "started_at": "2026-08-04T00:00:00+00:00",
                "completed_at": "2026-08-04T00:00:00+00:00",
                "failure_class": None,
                "failure_message": None,
            }
        return CommandResult(0)


def _write_manifest(root: Path, migration_ids):
    migrations_dir = root / "migrations"
    migrations_dir.mkdir(parents=True)
    for migration_id in migration_ids:
        (migrations_dir / migration_id).write_text("SELECT 1;\n", encoding="utf-8")
    payload = {
        "version": 1,
        "migrations": [
            {"sequence": sequence, "id": migration_id}
            for sequence, migration_id in enumerate(migration_ids, start=1)
        ],
    }
    (migrations_dir / "migration_manifest.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


@pytest.fixture
def migration_root(tmp_path):
    _write_manifest(tmp_path, ["001_base.sql", "002_next.sql", "003_last.sql"])
    return tmp_path


def test_repository_manifest_covers_every_sql_file_and_keeps_duplicate_prefixes():
    root = Path(__file__).resolve().parents[1]
    migrations = load_manifest(root)

    assert len(migrations) == len(list((root / "migrations").glob("*.sql")))
    assert [migration.migration_id for migration in migrations[:2]] == [
        "001_shared_state_tables.sql",
        "001_pg_schema.sql",
    ]
    assert {
        migration.migration_id
        for migration in migrations
        if migration.migration_id.startswith("009_")
    } == {
        "009_conversation_summary.sql",
        "009_uploaded_files_meta.sql",
    }
    assert {
        migration.migration_id
        for migration in migrations
        if migration.migration_id.startswith("010_")
    } == {
        "010_manufacturing_to_autorepair_permissions.sql",
        "010_uploaded_files_task_queue.sql",
    }
    assert migrations[-1].migration_id == "040_agent_default_tag_scope.sql"


def test_provider_governance_migration_is_atomic_and_registered():
    root = Path(__file__).resolve().parents[1]
    migration = root / "migrations" / "036_provider_governance.sql"
    body = transaction_body_for_migration(migration.read_text(encoding="utf-8"))
    manifest = load_manifest(root)

    assert any(item.migration_id == migration.name for item in manifest)
    assert "provider_call_leases" in body
    assert "provider_waiters" in body
    assert "provider_circuit_state" in body
    assert "concurrency_limit INTEGER NOT NULL" in body
    assert "priority IN (0, 10, 20)" in body


def test_workflow_retirement_migration_is_atomic_and_registered():
    root = Path(__file__).resolve().parents[1]
    migration = root / "migrations" / "037_remove_dag_workflow.sql"
    body = transaction_body_for_migration(migration.read_text(encoding="utf-8"))
    manifest = load_manifest(root)

    assert any(item.migration_id == migration.name for item in manifest)
    assert "workflow:read" in body
    assert "workflow:write" in body
    assert body.index("DROP TABLE IF EXISTS workflow_runs") < body.index(
        "DROP TABLE IF EXISTS workflow_definitions"
    )


def test_manifest_rejects_missing_or_duplicate_entries(tmp_path):
    _write_manifest(tmp_path, ["001_base.sql", "002_next.sql"])
    manifest_path = tmp_path / "migrations" / "migration_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["migrations"] = [{"sequence": 1, "id": "001_base.sql"}]
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ManifestError, match="missing"):
        load_manifest(tmp_path)

    payload["migrations"] = [
        {"sequence": 1, "id": "001_base.sql"},
        {"sequence": 2, "id": "001_base.sql"},
    ]
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ManifestError, match="duplicate"):
        load_manifest(tmp_path)


def test_apply_records_history_and_repeat_is_a_noop(migration_root):
    fake = _FakePsql()
    runner = MigrationRunner(migration_root, executor=fake)

    first_plan = runner.apply(backup_acknowledged=True)
    assert len(first_plan.pending) == 3
    assert fake.executed_files == ["001_base.sql", "002_next.sql", "003_last.sql"]
    assert {row["state"] for row in fake.history.values()} == {"applied"}

    second_plan = runner.apply(backup_acknowledged=True)
    assert second_plan.pending == ()
    assert fake.executed_files == ["001_base.sql", "002_next.sql", "003_last.sql"]


def test_checksum_drift_blocks_before_any_later_sql(migration_root):
    fake = _FakePsql()
    MigrationRunner(migration_root, executor=fake).apply(backup_acknowledged=True)
    (migration_root / "migrations" / "002_next.sql").write_text(
        "SELECT 2;\n", encoding="utf-8"
    )

    with pytest.raises(ChecksumDriftError, match="002_next.sql"):
        MigrationRunner(migration_root, executor=fake).plan()
    assert fake.executed_files == ["001_base.sql", "002_next.sql", "003_last.sql"]


def test_failure_is_recorded_and_stops_before_later_migrations(migration_root):
    fake = _FakePsql(fail_migration="002_next.sql")
    runner = MigrationRunner(migration_root, executor=fake)

    with pytest.raises(MigrationApplyError, match="002_next.sql"):
        runner.apply(backup_acknowledged=True)
    assert fake.executed_files == ["001_base.sql", "002_next.sql"]
    assert fake.history["001_base.sql"]["state"] == "applied"
    assert fake.history["002_next.sql"]["state"] == "failed"
    with pytest.raises(DatabaseStateError, match="unresolved failed migration"):
        runner.plan()


def test_apply_requires_backup_acknowledgement_before_database_access(migration_root):
    fake = _FakePsql()
    runner = MigrationRunner(migration_root, executor=fake)

    with pytest.raises(BackupAcknowledgementError):
        runner.apply(backup_acknowledged=False)
    assert fake.calls == []


def test_unknown_existing_database_without_history_fails_closed(migration_root):
    fake = _FakePsql(user_objects=1)
    with pytest.raises(DatabaseStateError, match="no migration history"):
        MigrationRunner(migration_root, executor=fake).plan()
    assert fake.executed_files == []


def test_baseline_records_only_an_explicit_verified_manifest_prefix(migration_root):
    fake = _FakePsql(user_objects=1)
    runner = MigrationRunner(migration_root, executor=fake)

    with pytest.raises(BackupAcknowledgementError):
        runner.baseline(through="002_next.sql", backup_acknowledged=False)
    assert fake.calls == []

    assert runner.baseline(through="002_next.sql", backup_acknowledged=True) == 2
    assert set(fake.history) == {"001_base.sql", "002_next.sql"}
    assert [migration.migration_id for migration in runner.plan().pending] == [
        "003_last.sql"
    ]


def test_status_reports_a_failed_history_row_without_permitting_apply(migration_root):
    fake = _FakePsql(fail_migration="002_next.sql")
    runner = MigrationRunner(migration_root, executor=fake)

    with pytest.raises(MigrationApplyError):
        runner.apply(backup_acknowledged=True)
    assert (
        next(row for row in runner.status() if row["migration_id"] == "002_next.sql")[
            "state"
        ]
        == "failed"
    )
    with pytest.raises(DatabaseStateError, match="unresolved failed migration"):
        runner.plan()


def test_status_does_not_render_empty_applied_failure_as_a_message(migration_root):
    fake = _FakePsql(user_objects=1)
    runner = MigrationRunner(migration_root, executor=fake)

    runner.baseline(through="002_next.sql", backup_acknowledged=True)

    applied = next(row for row in runner.status() if row["migration_id"] == "001_base.sql")
    assert applied["state"] == "applied"
    assert applied["failure_message"] is None


def test_verified_baseline_records_prefix_then_upgrades_remaining_migrations(
    migration_root,
):
    fake = _FakePsql(user_objects=1)
    runner = MigrationRunner(migration_root, executor=fake)

    assert runner.baseline(through="002_next.sql", backup_acknowledged=True) == 2
    assert fake.executed_files == []
    assert (
        runner.apply(backup_acknowledged=True).pending[0].migration_id == "003_last.sql"
    )
    assert fake.executed_files == ["003_last.sql"]


def test_connection_url_and_failure_output_are_redacted():
    env = connection_environment(
        {
            "DATABASE_URL": "postgresql://release_user:secret-value@db.example:5433/release?sslmode=require"
        }
    )
    assert env["PGHOST"] == "db.example"
    assert env["PGPORT"] == "5433"
    assert env["PGUSER"] == "release_user"
    assert env["PGDATABASE"] == "release"
    assert env["PGSSLMODE"] == "require"
    assert env["PGCLIENTENCODING"] == "UTF8"

    explicit_encoding = connection_environment({"PGCLIENTENCODING": "LATIN1"})
    assert explicit_encoding["PGCLIENTENCODING"] == "LATIN1"

    output = sanitize_failure(
        "could not connect postgresql://release_user:secret-value@db.example/release password=secret-value"
    )
    assert "secret-value" not in output
    assert "postgresql://" in output


def test_connection_url_forwards_tls_paths_and_connect_timeout_without_diagnostic_leakage():
    env = connection_environment({
        "DATABASE_URL": "postgresql://u:secret@db.example/app?sslrootcert=%2Fprivate%2Fca.pem&sslcert=%2Fprivate%2Fclient.pem&sslkey=%2Fprivate%2Fclient.key&connect_timeout=9",
    })
    assert env["PGSSLROOTCERT"] == "/private/ca.pem"
    assert env["PGSSLCERT"] == "/private/client.pem"
    assert env["PGSSLKEY"] == "/private/client.key"
    assert env["PGCONNECT_TIMEOUT"] == "9"
    assert "/private/client.key" not in sanitize_failure("sslkey=/private/client.key")


@pytest.mark.parametrize("sql", [
    "BEGIN; SELECT 1; COMMIT;",
    "SELECT 1;",
])
def test_transaction_body_accepts_only_an_optional_outer_wrapper(sql):
    body = transaction_body_for_migration(sql)
    assert "SELECT 1" in body
    assert "COMMIT" not in body


@pytest.mark.parametrize("sql", [
    "BEGIN; SELECT 1;",
    "BEGIN; BEGIN; SELECT 1; COMMIT; COMMIT;",
    "CREATE INDEX CONCURRENTLY idx ON example(id);",
    "VACUUM example;",
])
def test_transaction_body_rejects_unsafe_migration_sql(sql):
    with pytest.raises(MigrationApplyError):
        transaction_body_for_migration(sql)


def test_database_safe_failure_preserves_portable_diagnostic_text():
    assert database_safe_failure("错误: 权限不足") == r"\u9519\u8bef: \u6743\u9650\u4e0d\u8db3"
