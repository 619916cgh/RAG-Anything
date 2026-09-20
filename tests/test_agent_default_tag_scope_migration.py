import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_agent_default_tag_scope_migration_is_registered():
    migration = ROOT / "migrations" / "040_agent_default_tag_scope.sql"
    manifest = json.loads(
        (ROOT / "migrations" / "migration_manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert {
        "sequence": 43,
        "id": migration.name,
    } in manifest["migrations"]
    sql = migration.read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS default_tag_id BIGINT" in sql
    assert "chk_agents_default_tag_id_positive" in sql
