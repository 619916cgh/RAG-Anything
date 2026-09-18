import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_agent_answer_completeness_guard_migration_is_registered():
    migration = (
        ROOT / "migrations" / "039_agent_answer_completeness_guard.sql"
    )
    manifest = json.loads(
        (ROOT / "migrations" / "migration_manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert {
        "sequence": 42,
        "id": migration.name,
    } in manifest["migrations"]
    sql = migration.read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS answer_completeness_guard_enabled" in sql
    assert "BOOLEAN NOT NULL DEFAULT FALSE" in sql
