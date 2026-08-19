#!/usr/bin/env python3
"""Run the fixed disposable Compose acceptance profile.

This command owns the Compose project, credentials, temporary files, and cleanup.
It never accepts arbitrary stage commands and never reads the repository .env.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "tests" / "acceptance" / "compose.yml"
ISOLATED_MARKERS = ("staging", "preprod", "acceptance", "ci", "test")
UNSAFE_MARKERS = ("production", "live")


def _safe_target(value: str) -> str:
    value = str(value or "").strip().lower()
    if not value or any(marker in value for marker in UNSAFE_MARKERS) or not any(marker in value for marker in ISOLATED_MARKERS):
        raise ValueError("target must be an isolated non-production identifier")
    return value


def _require_clean_detached_commit(commit: str) -> str:
    """Bind acceptance to one immutable checkout, never a dirty worktree."""
    if not commit or len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit.lower()):
        raise ValueError("--commit must be a full 40-character Git SHA")
    resolved = _run(["git", "rev-parse", "--verify", f"{commit}^{{commit}}"], env=os.environ.copy()).stdout.strip()
    head = _run(["git", "rev-parse", "HEAD"], env=os.environ.copy()).stdout.strip()
    branch = _run(["git", "symbolic-ref", "-q", "HEAD"], env=os.environ.copy())
    status = _run(["git", "status", "--porcelain=v1", "--untracked-files=all"], env=os.environ.copy()).stdout.strip()
    if resolved != commit or head != commit or branch.returncode == 0 or status:
        raise ValueError("acceptance requires a clean detached checkout at --commit")
    return commit


def _secret() -> str:
    return secrets.token_urlsafe(24)


def _run(cmd: list[str], *, env: dict[str, str], timeout: int = 180, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout, check=False)


def _require_local_docker(env: dict[str, str]) -> None:
    if env.get("DOCKER_HOST") or env.get("DOCKER_CONTEXT"):
        raise ValueError("DOCKER_HOST and DOCKER_CONTEXT must be unset for local acceptance")
    context = _run(["docker", "context", "show"], env=env, timeout=20).stdout.strip()
    if context != "desktop-linux":
        raise ValueError("Docker context must be desktop-linux")


def _require_image_revision(image: str, commit: str, env: dict[str, str]) -> None:
    inspected = _run(["docker", "image", "inspect", image, "--format", "{{index .Config.Labels \"org.opencontainers.image.revision\"}}"], env=env, timeout=20)
    if inspected.returncode or inspected.stdout.strip() != commit:
        raise ValueError("acceptance app image is missing the requested commit revision label")


def _stage(name: str, fn, evidence: list[dict[str, object]]) -> bool:
    started = time.monotonic()
    try:
        detail = fn()
        ok = True
    except Exception as exc:  # evidence deliberately stores only a bounded class
        detail = type(exc).__name__
        ok = False
    evidence.append({"name": name, "outcome": "passed" if ok else "failed", "duration_seconds": round(time.monotonic() - started, 3), "detail": "" if ok else str(detail)[:160]})
    return ok


def run(target_id: str, workdir: Path, commit: str, *, timeout: int = 180) -> dict[str, object]:
    target = _safe_target(target_id)
    revision = _require_clean_detached_commit(commit)
    temp_root = Path(tempfile.gettempdir()).resolve()
    workdir = workdir.resolve()
    if temp_root not in workdir.parents or any(marker in str(workdir).lower() for marker in UNSAFE_MARKERS):
        raise ValueError("working directory must be an isolated descendant of the system temp directory")
    workdir.mkdir(parents=True, exist_ok=False)
    run_id = secrets.token_hex(8)
    project = f"ragaccept_{run_id}"
    port = str(18080 + secrets.randbelow(1000))
    pg_port = str(19080 + secrets.randbelow(1000))
    password = _secret()
    env = os.environ.copy()
    _require_local_docker(env)
    for key in ("DATABASE_URL", "POSTGRES_PASSWORD", "DEFAULT_ADMIN_PASSWORD", "JWT_SECRET", "JWT_REFRESH_SECRET"):
        env.pop(key, None)
    env.update({
        "ACCEPTANCE_RUN_ID": run_id, "ACCEPTANCE_RUN_DIR": str(workdir), "ACCEPTANCE_HTTP_PORT": port, "ACCEPTANCE_PG_PORT": pg_port,
        "ACCEPTANCE_APP_IMAGE": os.getenv("ACCEPTANCE_APP_IMAGE", ""),
        "ACCEPTANCE_POSTGRES_IMAGE": os.getenv("ACCEPTANCE_POSTGRES_IMAGE", "pgvector/pgvector:pg16"),
        "ACCEPTANCE_REDIS_IMAGE": os.getenv("ACCEPTANCE_REDIS_IMAGE", "redis:7-alpine"),
        "ACCEPTANCE_NGINX_IMAGE": os.getenv("ACCEPTANCE_NGINX_IMAGE", "nginx:alpine"),
        "POSTGRES_USER": "acceptance", "POSTGRES_PASSWORD": password, "POSTGRES_DATABASE": f"acceptance_{run_id}",
        "DATABASE_URL": f"postgresql://acceptance:{password}@postgres:5432/acceptance_{run_id}",
        "JWT_SECRET": _secret(), "JWT_REFRESH_SECRET": _secret(),
        "DEFAULT_ADMIN_USERNAME": "acceptance_admin", "DEFAULT_ADMIN_PASSWORD": _secret(),
    })
    if not env["ACCEPTANCE_APP_IMAGE"]:
        raise ValueError("ACCEPTANCE_APP_IMAGE must name an immutable image built from --commit")
    _require_image_revision(env["ACCEPTANCE_APP_IMAGE"], revision, env)
    (workdir / "pgvector-init.sql").write_text((ROOT / "tests" / "acceptance" / "pgvector-init.sql").read_text(encoding="utf-8"), encoding="utf-8")
    (workdir / "nginx.conf").write_text((ROOT / "tests" / "acceptance" / "nginx.conf").read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copy2(ROOT / "tests" / "perf" / "mock_provider.py", workdir / "mock_provider.py")
    evidence: list[dict[str, object]] = []
    compose = ["docker", "compose", "-p", project, "--env-file", str(workdir / "compose.env"), "-f", str(COMPOSE)]
    (workdir / "compose.env").write_text("\n".join(f"{k}={v}" for k, v in env.items() if k.startswith("ACCEPTANCE_") or k in {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DATABASE", "DATABASE_URL", "JWT_SECRET", "JWT_REFRESH_SECRET", "DEFAULT_ADMIN_USERNAME", "DEFAULT_ADMIN_PASSWORD"}), encoding="utf-8")
    result: dict[str, object] = {"schema_version": 1, "target_id": target, "run_id": run_id, "project": project, "revision": revision, "non_production": True, "stages": evidence, "deferred": ["external-provider", "video", "browser-uat", "production-approval"]}
    try:
        def compose_up():
            result = _run(compose + ["up", "-d"], env=env, timeout=timeout)
            if result.returncode:
                raise RuntimeError("compose-up")
        if not _stage("compose-up", compose_up, evidence):
            return result | {"release_recommendation": "not-releasable"}
        base = f"http://127.0.0.1:{port}"
        def health():
            for path in ("/api/live", "/api/ready", "/api/health"):
                with urllib.request.urlopen(base + path, timeout=10) as response:
                    if response.status != 200: raise RuntimeError(path)
        if not _stage("health", health, evidence):
            return result | {"release_recommendation": "not-releasable"}
        stage_env = dict(env)
        parsed = urlsplit(env["DATABASE_URL"])
        stage_env["MIGRATION_TEST_DATABASE_URL"] = urlunsplit((parsed.scheme, f"acceptance:{password}@127.0.0.1:{pg_port}", parsed.path, parsed.query, parsed.fragment))
        stage_env["DATABASE_URL"] = stage_env["MIGRATION_TEST_DATABASE_URL"]
        def pytest_stage(nodeid: str):
            result = _run([sys.executable, "-m", "pytest", "-q", nodeid], env=stage_env, timeout=timeout)
            if result.returncode:
                raise RuntimeError(f"pytest-{nodeid}")
        migration_nodes = (
            "tests/test_pg_migration_runner_integration.py::test_complete_chain_fresh_install_and_repeat",
            "tests/test_pg_migration_runner_integration.py::test_recorded_checkpoint_upgrades_only_the_new_migration",
            "tests/test_pg_migration_runner_integration.py::test_complete_chain_fresh_install_and_repeat",
            "tests/test_pg_migration_runner_integration.py::test_failing_migration_stops_before_later_file",
        )
        for name, nodeid in zip(("migration-fresh", "migration-upgrade", "migration-repeat", "migration-failure"), migration_nodes):
            if not _stage(name, lambda nodeid=nodeid: pytest_stage(nodeid), evidence):
                return result | {"release_recommendation": "not-releasable"}
        if not _stage("roles", lambda: pytest_stage("tests/test_pg_authenticated_api_integration.py"), evidence):
            return result | {"release_recommendation": "not-releasable"}
        _stage("worker-retrieval", lambda: (_ for _ in ()).throw(RuntimeError("worker-fixture-requires-controlled-marker-and-vector-model")), evidence)
        result["release_recommendation"] = "isolated-preproduction-pass" if all(x["outcome"] == "passed" for x in evidence) else "not-releasable"
        return result
    finally:
        cleanup = _run(compose + ["down", "--volumes", "--remove-orphans"], env=env, timeout=timeout)
        evidence.append({"name": "cleanup", "outcome": "passed" if cleanup.returncode == 0 else "failed", "duration_seconds": 0, "detail": "" if cleanup.returncode == 0 else "compose-cleanup"})
        result["release_recommendation"] = "isolated-preproduction-pass" if all(x["outcome"] == "passed" for x in evidence) else "not-releasable"
        (workdir / "evidence.json").write_text(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        for transient in ("compose.env", "pgvector-init.sql", "nginx.conf", "mock_provider.py"):
            (workdir / transient).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--non-production", action="store_true", required=True)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--working-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if not args.non_production: raise ValueError("--non-production is required")
        result = run(args.target_id, args.working_dir, args.commit)
    except Exception as exc:
        result = {"schema_version": 1, "release_recommendation": "not-releasable", "failure_class": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result.get("release_recommendation") == "isolated-preproduction-pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
