#!/usr/bin/env python3
"""Read-only preflight for a Stage 3 offline release bundle.

This command deliberately does not import images, create Docker resources,
open a database connection, load an environment file, or read a secret value.
It is safe to run on a future Linux host before an operator authorizes a
deployment.  ``--fixture`` makes every host observation injectable for local
contract tests.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


MIN_CPU = 4
MIN_MEMORY_BYTES = 8 * 1024**3
MIN_DISK_BYTES = 40 * 1024**3
REQUIRED_ARCHIVES = ("candidate.tar", "rollback.tar", "postgres.tar", "redis.tar", "nginx.tar")
REQUIRED_SECRETS = frozenset({
    "DATABASE_URL", "JWT_SECRET", "JWT_REFRESH_SECRET", "DEFAULT_ADMIN_PASSWORD",
    "LLM_BINDING_API_KEY", "EMBEDDING_API_KEY", "PGPASSFILE", "SSH_KEY_REFERENCE",
    "PROMETHEUS_SCRAPE_CONFIG_REFERENCE", "BACKUP_CUSTODY_REFERENCE",
})
SECRET_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True)
class Observation:
    system: str
    machine: str
    docker_engine: str
    compose: str
    cpu_count: int
    memory_bytes: int
    disk_free_bytes: int
    docker_data_free_bytes: int
    occupied_ports: frozenset[int]


def _command(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def _memory_bytes() -> int:
    try:
        pages = os.sysconf("SC_PAGE_SIZE")
        total = os.sysconf("SC_PHYS_PAGES")
        return int(pages) * int(total)
    except (AttributeError, OSError, ValueError):
        return 0


def _docker_data_directory() -> Path | None:
    value = _command("docker", "info", "--format", "{{.DockerRootDir}}")
    return Path(value) if value else None


def _port_is_occupied(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def observe_host() -> Observation:
    docker_root = _docker_data_directory()
    docker_free = shutil.disk_usage(docker_root).free if docker_root and docker_root.exists() else 0
    root_free = shutil.disk_usage(Path("/")).free
    return Observation(
        system=platform.system(),
        machine=platform.machine().lower(),
        docker_engine=_command("docker", "version", "--format", "{{.Server.Version}}"),
        compose=_command("docker", "compose", "version", "--short"),
        cpu_count=os.cpu_count() or 0,
        memory_bytes=_memory_bytes(),
        disk_free_bytes=root_free,
        docker_data_free_bytes=docker_free,
        occupied_ports=frozenset(port for port in (80, 443) if _port_is_occupied(port)),
    )


def observation_from_fixture(payload: dict[str, Any]) -> Observation:
    host = payload.get("host")
    if not isinstance(host, dict):
        raise ValueError("PREFLIGHT_FIXTURE_INVALID")
    try:
        return Observation(
            system=str(host["system"]), machine=str(host["machine"]).lower(),
            docker_engine=str(host["docker_engine"]), compose=str(host["compose"]),
            cpu_count=int(host["cpu_count"]), memory_bytes=int(host["memory_bytes"]),
            disk_free_bytes=int(host["disk_free_bytes"]), docker_data_free_bytes=int(host["docker_data_free_bytes"]),
            occupied_ports=frozenset(int(port) for port in host.get("occupied_ports", [])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("PREFLIGHT_FIXTURE_INVALID") from exc


def _check(code: str, passed: bool, *, status: str | None = None) -> dict[str, str]:
    return {"code": code, "status": status or ("passed" if passed else "failed")}


def _read_secret_names(bundle: Path) -> set[str]:
    path = bundle / "requirements" / "secret-references.txt"
    if not path.is_file():
        raise ValueError("PREFLIGHT_SECRET_REFERENCES_MISSING")
    names = {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
    if any(not SECRET_NAME.fullmatch(name) for name in names) or not REQUIRED_SECRETS.issubset(names):
        raise ValueError("PREFLIGHT_SECRET_REFERENCES_INVALID")
    return names


def _archives_are_readable(archives: Path) -> bool:
    try:
        for archive in REQUIRED_ARCHIVES:
            path = archives / archive
            if not path.is_file() or path.stat().st_size <= 0:
                return False
            with path.open("rb") as stream:
                if not stream.read(1):
                    return False
    except OSError:
        return False
    return True


def preflight(bundle: Path, *, observation: Observation | None = None, ports: Iterable[int] = (80, 443)) -> dict[str, Any]:
    """Assess only local metadata and return stable status codes, never values."""
    bundle = bundle.resolve()
    if not bundle.is_dir():
        return {"status": "failed", "checks": [_check("PREFLIGHT_BUNDLE_MISSING", False)]}
    host = observation or observe_host()
    requested_ports = tuple(int(port) for port in ports)
    if not requested_ports or any(port < 1 or port > 65535 for port in requested_ports):
        return {"status": "failed", "checks": [_check("PREFLIGHT_PORTS_INVALID", False)]}
    checks = [
        _check("PREFLIGHT_PLATFORM", host.system == "Linux" and host.machine in {"x86_64", "amd64"}),
        _check("PREFLIGHT_DOCKER_ENGINE", bool(host.docker_engine)),
        _check("PREFLIGHT_DOCKER_COMPOSE_V2", bool(host.compose) and not host.compose.startswith("1.")),
        _check("PREFLIGHT_CPU", host.cpu_count >= MIN_CPU),
        _check("PREFLIGHT_MEMORY", host.memory_bytes >= MIN_MEMORY_BYTES),
        _check("PREFLIGHT_DISK", host.disk_free_bytes >= MIN_DISK_BYTES),
        _check("PREFLIGHT_DOCKER_DATA_DISK", host.docker_data_free_bytes >= MIN_DISK_BYTES),
        _check("PREFLIGHT_PORTS", not (host.occupied_ports & frozenset(requested_ports))),
    ]
    archives = bundle / "images"
    checks.append(_check("PREFLIGHT_ARCHIVES", _archives_are_readable(archives)))
    try:
        _read_secret_names(bundle)
        checks.append(_check("PREFLIGHT_SECRET_REFERENCES", True))
    except ValueError as exc:
        checks.append(_check(str(exc), False))
    resource_capacity = host.cpu_count >= MIN_CPU and host.memory_bytes >= MIN_MEMORY_BYTES and host.disk_free_bytes >= MIN_DISK_BYTES and host.docker_data_free_bytes >= MIN_DISK_BYTES
    runbook_assets = (bundle / "runbook.md").is_file() and (bundle / "requirements" / "host-prerequisites.txt").is_file()
    checks.extend([
        _check("PREFLIGHT_RESOURCE_PLAN_POSTGRES", resource_capacity and runbook_assets),
        _check("PREFLIGHT_RESOURCE_PLAN_REDIS", resource_capacity and runbook_assets),
        _check("PREFLIGHT_RESOURCE_PLAN_APP", resource_capacity and runbook_assets),
        _check("PREFLIGHT_RESOURCE_PLAN_WORKER", resource_capacity and runbook_assets),
        _check("PREFLIGHT_RESOURCE_PLAN_NGINX", resource_capacity and runbook_assets),
        _check("PREFLIGHT_DNS", False, status="pending-external"),
        _check("PREFLIGHT_TLS", False, status="pending-external"),
        _check("PREFLIGHT_PROVIDER", False, status="pending-external"),
        _check("PREFLIGHT_BACKUP_CUSTODY", False, status="pending-external"),
    ])
    mandatory = [check for check in checks if check["status"] != "pending-external"]
    return {"status": "passed" if all(check["status"] == "passed" for check in mandatory) else "failed", "checks": checks}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, help="test-only observation JSON; no host commands are run")
    parser.add_argument("--ports", type=int, nargs="+", default=(80, 443), help="ports to check without starting a listener")
    args = parser.parse_args(argv)
    try:
        fixture = json.loads(args.fixture.read_text(encoding="utf-8")) if args.fixture else None
        result = preflight(args.bundle, observation=observation_from_fixture(fixture) if fixture is not None else None, ports=args.ports)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        result = {"status": "failed", "checks": [_check(str(exc) if str(exc).startswith("PREFLIGHT_") else "PREFLIGHT_INPUT_INVALID", False)]}
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
