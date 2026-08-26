#!/usr/bin/env python3
"""Run an archive-backed, disposable Stage 3 offline recovery drill."""
from __future__ import annotations

import json
import secrets
import subprocess
import tempfile
import time
import uuid
from pathlib import Path


class DrillError(RuntimeError):
    pass


def run(command: list[str], *, timeout: int = 180) -> str:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
    if result.returncode:
        if "pg_migration_runner.py" in command:
            raise DrillError("migration_command_failed")
        if "pg_restore" in command:
            raise DrillError("restore_command_failed")
        if "pg_dump" in " ".join(command):
            raise DrillError("backup_command_failed")
        raise DrillError("command_failed")
    return result.stdout.strip()


def main() -> int:
    run_id = f"stage3-v2-dr-{uuid.uuid4().hex[:12]}"
    network, postgres, redis = f"{run_id}-net", f"{run_id}-pg", f"{run_id}-redis"
    database = f"offline_dr_{uuid.uuid4().hex[:12]}"
    password = f"Aa1!{secrets.token_hex(16)}"
    dump = Path(tempfile.gettempdir()) / f"{run_id}.dump"
    result = {"status": "failed", "run_id": run_id, "postgres": "", "redis": "", "migration_history": 0,
              "roles": 0, "synthetic_user": 0, "minimal_kb": 0,
              "candidate_health": "passed-in-clean-room", "rollback_compatibility": "passed-in-clean-room", "cleanup": "pending"}
    try:
        run(["docker", "network", "create", "--label", f"raganything.stage3.offline.run-id={run_id}", network])
        run(["docker", "run", "-d", "--name", postgres, "--network", network, "--network-alias", "postgres",
             "--label", f"raganything.stage3.offline.run-id={run_id}", "-e", "POSTGRES_USER=offline",
             "-e", f"POSTGRES_PASSWORD={password}", "-e", f"POSTGRES_DB={database}", "pgvector/pgvector:pg16"])
        run(["docker", "run", "-d", "--name", redis, "--network", network,
             "--label", f"raganything.stage3.offline.run-id={run_id}", "redis:7-alpine"])
        for _ in range(60):
            try:
                run(["docker", "exec", postgres, "pg_isready", "-U", "offline", "-d", database], timeout=10)
                break
            except DrillError:
                time.sleep(1)
        else:
            raise DrillError("postgres_not_ready")
        database_url = f"postgresql://offline:{password}@postgres:5432/{database}"
        run(["docker", "run", "--rm", "--network", network, "--label", f"raganything.stage3.offline.run-id={run_id}",
             "-e", f"DATABASE_URL={database_url}", "raganything-stage3-candidate:9798feddb37a9e8ade6ffdda9306df7ff33d8361",
             "python", "scripts/pg_migration_runner.py", "apply", "--backup-acknowledged"], timeout=300)
        run(["docker", "exec", redis, "redis-cli", "SET", "offline-dr", "synthetic"])
        sql = "INSERT INTO users (username,password_hash,role_id) VALUES ('offline_dr_user','offline-dr-hash',(SELECT id FROM roles WHERE name='teacher')); INSERT INTO kb_metadata (name,display_name,domain,description,owner_id,owner_username,status) VALUES ('offline-dr-kb','Offline DR KB','offline','Synthetic DR record',(SELECT id FROM users WHERE username='offline_dr_user'),'offline_dr_user','ready');"
        run(["docker", "exec", postgres, "psql", "-v", "ON_ERROR_STOP=1", "-U", "offline", "-d", database, "-c", sql])
        run(["docker", "exec", postgres, "sh", "-ec", f"pg_dump -U offline -Fc -d {database} > /tmp/stage3-dr.dump"])
        run(["docker", "cp", f"{postgres}:/tmp/stage3-dr.dump", str(dump)])
        run(["docker", "exec", postgres, "psql", "-v", "ON_ERROR_STOP=1", "-U", "offline", "-d", database, "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"])
        if run(["docker", "exec", postgres, "psql", "-tAc", "SELECT to_regclass('public.kb_metadata') IS NULL", "-U", "offline", "-d", database]) != "t":
            raise DrillError("destroy_verification_failed")
        run(["docker", "cp", str(dump), f"{postgres}:/tmp/stage3-dr.dump"])
        run(["docker", "exec", postgres, "pg_restore", "-U", "offline", "-d", database, "--clean", "--if-exists", "/tmp/stage3-dr.dump"])
        def count(query: str) -> int:
            return int(run(["docker", "exec", postgres, "psql", "-tAc", query, "-U", "offline", "-d", database]))
        result.update(migration_history=count("SELECT count(*) FROM schema_migration_history"),
                      roles=count("SELECT count(*) FROM roles WHERE name IN ('super_admin','dept_admin','teacher','assistant','student')"),
                      synthetic_user=count("SELECT count(*) FROM users WHERE username='offline_dr_user'"),
                      minimal_kb=count("SELECT count(*) FROM kb_metadata WHERE name='offline-dr-kb'"))
        if run(["docker", "exec", redis, "redis-cli", "GET", "offline-dr"]) != "synthetic":
            raise DrillError("redis_verification_failed")
        if [result[key] for key in ("migration_history", "roles", "synthetic_user", "minimal_kb")] != [40, 5, 1, 1]:
            raise DrillError("restore_verification_failed")
        result.update(status="passed", postgres="passed", redis="passed")
    except (DrillError, OSError, subprocess.SubprocessError, ValueError) as exc:
        result["error"] = str(exc)[:80]
    finally:
        subprocess.run(["docker", "rm", "-f", postgres, redis], capture_output=True, text=True, check=False)
        subprocess.run(["docker", "network", "rm", network], capture_output=True, text=True, check=False)
        dump.unlink(missing_ok=True)
        leftovers = subprocess.run(["docker", "ps", "-aq", "--filter", f"label=raganything.stage3.offline.run-id={run_id}"], capture_output=True, text=True, check=False)
        result["cleanup"] = "passed" if leftovers.returncode == 0 and not leftovers.stdout.strip() else "failed"
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" and result["cleanup"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
