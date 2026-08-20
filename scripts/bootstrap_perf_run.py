"""Create a disposable mock-backed workload for an isolated perf run.

Secrets and raw identifiers are written only below ``--run-dir``. Console
output is intentionally limited to stage names and HTTP status classes.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path
from urllib.parse import quote

import requests


def _inside_temp(path: Path) -> Path:
    root = path.resolve()
    temp = Path(os.getenv("TEMP", "/tmp")).resolve()
    if root == temp or temp not in root.parents:
        raise ValueError("run directory must be a child of the system temporary directory")
    return root


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        key, separator, value = line.partition("=")
        if separator and key:
            values[key] = value
    return values


def _request(session: requests.Session, method: str, url: str, *, timeout: float, **kwargs) -> dict:
    response = session.request(method, url, timeout=timeout, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"bootstrap HTTP {response.status_code} at {url.rsplit('/', 1)[-1]}")
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("bootstrap response was not JSON") from exc


def _suffix() -> str:
    return secrets.token_hex(6)


def _workload_name(run_id: str, index: int) -> str:
    return f"{run_id[-8:]}{index:03d}{_suffix()}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--users", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    if args.users < 1 or args.users > 50 or args.timeout <= 0:
        raise ValueError("users must be between 1 and 50 and timeout must be positive")

    run_dir = _inside_temp(Path(args.run_dir))
    env_file = Path(args.env_file).resolve()
    if env_file.parent != run_dir:
        raise ValueError("environment file must be in the run directory")
    values = _read_env(env_file)
    admin_name = values["DEFAULT_ADMIN_USERNAME"]
    admin_password = values["DEFAULT_ADMIN_PASSWORD"]
    run_id = values["PERF_RUN_ID"]
    base_url = args.base_url.rstrip("/")
    if not base_url.startswith("http://127.0.0.1:"):
        raise ValueError("base URL must use a loopback port")

    session = requests.Session()
    admin_login = _request(
        session,
        "POST",
        f"{base_url}/api/auth/login",
        timeout=args.timeout,
        json={"username": admin_name, "password": admin_password},
    )
    admin_token = str(admin_login["access_token"])
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    roles = _request(session, "GET", f"{base_url}/api/admin/roles", timeout=args.timeout, headers=admin_headers)["roles"]
    teacher_role = next((role for role in roles if role.get("name") == "teacher"), None)
    if not teacher_role:
        raise RuntimeError("teacher role is unavailable in the isolated database")

    records: list[dict[str, str]] = []
    for index in range(args.users):
        suffix = _workload_name(run_id, index)
        username = f"perf_{suffix}"[:48]
        password = "P!" + secrets.token_urlsafe(24)
        created = _request(
            session,
            "POST",
            f"{base_url}/api/admin/users",
            timeout=args.timeout,
            headers=admin_headers,
            json={"username": username, "password": password, "role_id": teacher_role["id"]},
        )
        if not created.get("user", {}).get("id"):
            raise RuntimeError("isolated user creation returned no user id")
        user_login = _request(
            session,
            "POST",
            f"{base_url}/api/auth/login",
            timeout=args.timeout,
            json={"username": username, "password": password},
        )
        user_token = str(user_login["access_token"])
        user_headers = {"Authorization": f"Bearer {user_token}"}
        kb = f"perf_kb_{suffix}"[:64]
        _request(
            session,
            "POST",
            f"{base_url}/api/kb/create?kb_name={quote(kb)}&label={quote('Performance run')}",
            timeout=args.timeout,
            headers=user_headers,
        )
        agent = _request(
            session,
            "POST",
            f"{base_url}/api/agents",
            timeout=args.timeout,
            headers=user_headers,
            json={
                "name": "Performance run agent",
                "kb_name": kb,
                "llm_model": "perf-mock",
                "agent_mode": "none",
                "query_mode": "hybrid",
                "enable_rerank": False,
            },
        )["agent"]
        records.append({
            "username": username,
            "password": password,
            "agent_id": str(agent["id"]),
            "kb": kb,
            "vu": index + 1,
        })

    # This application endpoint exercises the configured visual adapter; it
    # must remain mock-backed even though the direct query fixture is text only.
    _request(session, "GET", f"{base_url}/api/health/vision-embedding", timeout=args.timeout, headers=admin_headers)
    # The provider is internal-only. Its aggregate evidence is collected later
    # through the Compose network, avoiding a host port for the mock service.
    credentials_path = run_dir.joinpath("credentials.json")
    credentials_path.write_text(json.dumps(records), encoding="utf-8")
    credentials_path.chmod(0o600)
    run_dir.joinpath("bootstrap.json").write_text(
        json.dumps({"status": "ok", "run": run_id, "created": {"users": args.users, "kbs": args.users, "agents": args.users}, "vision_health": "requested"}),
        encoding="utf-8",
    )
    print(f"bootstrap: {args.users} isolated workloads created")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
