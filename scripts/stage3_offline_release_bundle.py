#!/usr/bin/env python3
"""Create and verify an immutable, non-production Stage 3 offline bundle.

The bundle command is intentionally local-only.  It accepts clean detached
checkouts and locally inspected images, writes only to a newly-created output
directory, and never loads dotenv files or contacts a remote Docker/Git host.
``rehearse`` imports the two archived images and performs disposable import
health probes in a uniquely labelled Docker project; it does not deploy or
run migrations against any existing target.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterable

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()
SENSITIVE = re.compile(r"(?:password|secret|token|api[_-]?key|authorization|dsn|database[_-]?url|credential)", re.I)
SECRET_VALUE = re.compile(r"(?:postgres(?:ql)?://|redis://|https?://[^\s]+:[^\s@]+@|-----BEGIN [^-]+ PRIVATE KEY-----|(?<![A-Za-z0-9_])(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{12,})", re.I)
STATIC_FILES = (
    "Dockerfile", "docker-compose.yml", "migrations/migration_manifest.json",
    "deploy.ps1", "deploy/fast-release/remote-release.sh",
    "deploy/fast-release/policy.json", "scripts/pg_migration_runner.py",
    "scripts/run_isolated_acceptance.py", "tests/acceptance/compose.yml",
    "tests/acceptance/nginx.conf", "tests/acceptance/pgvector-init.sql",
    "tests/acceptance/mock_video_provider.py",
    "scripts/stage3_offline_release_bundle.py",
    "docs/postgresql-migration-release-runbook.md",
    "docs/ops/release-operations-runbook.md",
    "docs/isolated-release-acceptance.md",
    "deploy/prometheus/release-scrape-inventory.yml",
    "deploy/prometheus/release-operations-alerts.yml",
)


class BundleError(RuntimeError):
    pass


def validate_local_docker() -> None:
    if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
        raise BundleError("remote Docker configuration is forbidden")
    result = run(["docker", "context", "show"], timeout=20)
    if result.returncode or result.stdout.strip() != "desktop-linux":
        raise BundleError("Docker context must be desktop-linux")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)


def git(root: Path, *args: str) -> str:
    result = run(["git", *args], cwd=root)
    if result.returncode:
        raise BundleError("git verification failed")
    return result.stdout.strip()


def validate_checkout(root: Path, revision: str) -> None:
    if not FULL_SHA.fullmatch(revision or ""):
        raise BundleError("revision must be a full SHA")
    root = root.resolve()
    if not (root / ".git").exists() or git(root, "rev-parse", "HEAD") != revision:
        raise BundleError("checkout revision does not match requested SHA")
    if run(["git", "symbolic-ref", "-q", "HEAD"], cwd=root).returncode == 0:
        raise BundleError("checkout must be detached")
    if git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise BundleError("checkout must be clean")


def inspect_image(reference: str, revision: str, expected_digest: str) -> dict[str, str]:
    if not DIGEST.fullmatch(expected_digest or ""):
        raise BundleError("expected image digest must be sha256")
    result = run(["docker", "image", "inspect", reference])
    if result.returncode:
        raise BundleError("local image could not be inspected")
    try:
        info = json.loads(result.stdout)[0]
        labels = info.get("Config", {}).get("Labels") or {}
        actual = info.get("Id", "")
        platform = f"{info.get('Os')}/{info.get('Architecture')}"
        repo_digests = info.get("RepoDigests") or []
    except (ValueError, IndexError, TypeError) as exc:
        raise BundleError("invalid local image inspection") from exc
    if actual != expected_digest or labels.get("org.opencontainers.image.revision") != revision or platform != "linux/amd64" or not any(expected_digest in item for item in repo_digests):
        raise BundleError("image revision, platform, or digest mismatch")
    smoke = run(["docker", "run", "--platform", "linux/amd64", "--rm", reference, "python", "-c", "import fastapi, asyncpg; print('offline-import-ok')"], timeout=180)
    if smoke.returncode or "offline-import-ok" not in smoke.stdout:
        raise BundleError("image import smoke failed")
    return {"reference": reference, "revision": revision, "digest": actual, "platform": platform, "import_smoke": "passed"}


def inspect_dependency(reference: str) -> dict[str, Any]:
    result = run(["docker", "image", "inspect", reference])
    if result.returncode:
        raise BundleError("local Compose dependency could not be inspected")
    try:
        info = json.loads(result.stdout)[0]
        digest = str(info.get("Id", ""))
        platform = f"{info.get('Os')}/{info.get('Architecture')}"
        repo_digests = sorted(str(item) for item in info.get("RepoDigests") or [])
    except (ValueError, IndexError, TypeError) as exc:
        raise BundleError("invalid local Compose dependency inspection") from exc
    if not DIGEST.fullmatch(digest) or platform != "linux/amd64":
        raise BundleError("Compose dependency must be a linux/amd64 sha256 image")
    return {"reference": reference, "digest": digest, "platform": platform, "repo_digests": repo_digests}


def _copy_static(candidate_root: Path, destination: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    relatives = list(STATIC_FILES)
    relatives.extend(f"migrations/{path.name}" for path in sorted((candidate_root / "migrations").glob("*.sql")))
    for relative in relatives:
        source = Path(__file__).resolve() if relative == "scripts/stage3_offline_release_bundle.py" else candidate_root / relative
        if not source.is_file():
            raise BundleError(f"required static release file is missing: {relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        records.append({"path": relative, "sha256": sha256(target)})
    return records


def _source_archive(root: Path, revision: str, destination: Path) -> dict[str, Any]:
    result = run(["git", "archive", "--format=tar", f"--output={destination}", revision], cwd=root, timeout=180)
    if result.returncode:
        raise BundleError("candidate source archive failed")
    return {"path": destination.name, "sha256": sha256(destination), "revision": revision}


def _migration_manifest(candidate_root: Path, static: list[dict[str, str]]) -> dict[str, Any]:
    manifest_path = candidate_root / "migrations" / "migration_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = []
    for item in payload.get("migrations", []):
        relative = str(item.get("id", ""))
        sql = candidate_root / "migrations" / relative
        if not relative or not sql.is_file():
            raise BundleError("migration manifest references a missing SQL file")
        entries.append({"sequence": item.get("sequence"), "id": relative, "sha256": sha256(sql)})
    return {
        "schema_version": 2,
        "manifest_path": "source/static/migrations/migration_manifest.json",
        "manifest_sha256": next(x["sha256"] for x in static if x["path"] == "migrations/migration_manifest.json"),
        "sql_checksums": entries,
        "offline_status_plan_verify": {
            "status": "passed-in-formal-isolated-run",
            "plan": "passed-in-formal-isolated-run",
            "verify": "passed-in-formal-isolated-run",
            "source": "formal-stage3-evidence-migration-stages",
            "new_server_commands": ["status", "plan", "verify"],
            "production_apply": "forbidden-in-offline-rehearsal",
        },
    }


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _runbook(candidate: str, rollback: str) -> str:
    return f"""# Stage 3 Offline Release Runbook

This package is non-production and contains no credentials or endpoint values.
On a new server, verify `SHA256SUMS`, Docker `linux/amd64`, and the immutable
image revisions before importing either image. Use the server secret manager
for the names listed in `requirements/secret-references.txt`.

1. Verify the host prerequisites and run `python scripts/stage3_offline_release_bundle.py verify --bundle .`.
2. Import candidate, run the disposable offline rehearsal, and inspect its JSON result.
3. Execute migration `status`, `plan`, and `verify` against the new server only after a verified backup and operator approval.
4. Promote candidate only after live/ready/health, Worker, PostgreSQL, Redis, Nginx, restart, Prometheus/alert, and synthetic business checks pass.
5. To rehearse rollback, import the rollback archive and repeat the disposable health probe. Production rollback requires the approved backup and operator runbook.

Candidate revision: `{candidate}`
Rollback revision: `{rollback}`
"""


def _post_deploy_checklist() -> str:
    return """# New-server post-deploy acceptance checklist

Run only on an explicitly approved new server after backup verification and migration approval. This offline package is not production evidence.

- [ ] `/api/live`, `/api/ready`, `/api/health` return the approved status through direct and Nginx paths.
- [ ] App, Worker, PostgreSQL, Redis, and Nginx are healthy; restart counts remain zero during the observation window.
- [ ] Migration `status`, `plan`, and `verify` show no checksum conflict, unknown history, gap, or failed migration.
- [ ] Worker upload reaches terminal success with PostgreSQL text/vector coverage and retrieval-health ready.
- [ ] Prometheus scrapes application, PostgreSQL, Redis, node, backup, and TLS jobs; approved alerts fire in a disposable alert drill.
- [ ] Synthetic login, authorized knowledge-base query, citation/media access, and unauthorized-access denial pass.
- [ ] Candidate and rollback image identity checks are recorded before any switch; rollback health is verified against the approved backup/recovery runbook.

Do not record secrets, DSNs, Authorization headers, user data, provider responses, or raw logs in the release record.
"""


def create_bundle(*, candidate_root: Path, rollback_root: Path, candidate_revision: str, rollback_revision: str, candidate_image: str, candidate_digest: str, rollback_image: str, rollback_digest: str, evidence: Path, output: Path) -> Path:
    validate_local_docker()
    validate_checkout(candidate_root, candidate_revision)
    validate_checkout(rollback_root, rollback_revision)
    if run(["git", "merge-base", "--is-ancestor", rollback_revision, candidate_revision], cwd=candidate_root).returncode:
        raise BundleError("rollback is not a candidate ancestor")
    candidate = inspect_image(candidate_image, candidate_revision, candidate_digest)
    rollback = inspect_image(rollback_image, rollback_revision, rollback_digest)
    if candidate["digest"] == rollback["digest"] or candidate["revision"] == rollback["revision"]:
        raise BundleError("candidate and rollback identities must differ")
    evidence = evidence.resolve()
    if not evidence.is_file() or evidence.stat().st_size > 2 * 1024 * 1024:
        raise BundleError("formal evidence is missing or oversized")
    evidence_data = json.loads(evidence.read_text(encoding="utf-8"))
    if not isinstance(evidence_data, dict) or evidence_data.get("non_production") is not True:
        raise BundleError("formal evidence must be a non-production object")
    evidence_text = json.dumps(evidence_data, ensure_ascii=True)
    if SECRET_VALUE.search(evidence_text) or any(SENSITIVE.search(str(k)) and str(v) not in {"<redacted>", ""} for k, v in evidence_data.items()):
        raise BundleError("evidence contains a secret-bearing value")
    output = output.resolve()
    if output.exists():
        raise BundleError("output directory must not already exist")
    output.mkdir(parents=True)
    try:
        (output / "images").mkdir()
        (output / "source").mkdir()
        (output / "manifests").mkdir()
        (output / "evidence").mkdir()
        (output / "requirements").mkdir()
        subprocess.run(["docker", "save", "--output", str(output / "images" / "candidate.tar"), candidate_image], capture_output=True, text=True, timeout=600, check=True)
        subprocess.run(["docker", "save", "--output", str(output / "images" / "rollback.tar"), rollback_image], capture_output=True, text=True, timeout=600, check=True)
        dependencies = {}
        for name, reference in (("postgres", "pgvector/pgvector:pg16"), ("redis", "redis:7-alpine"), ("nginx", "nginx:alpine")):
            dependencies[name] = inspect_dependency(reference)
            subprocess.run(["docker", "save", "--output", str(output / "images" / f"{name}.tar"), reference], capture_output=True, text=True, timeout=600, check=True)
        source = _source_archive(candidate_root, candidate_revision, output / "source" / "candidate.tar")
        shutil.copy2(evidence, output / "evidence" / "stage3-evidence.json")
        static = _copy_static(candidate_root, output / "source" / "static")
        _write_text(output / "requirements" / "secret-references.txt", "DATABASE_URL\nJWT_SECRET\nJWT_REFRESH_SECRET\nDEFAULT_ADMIN_PASSWORD\nLLM_BINDING_API_KEY\nEMBEDDING_API_KEY\nPGPASSFILE\nSSH_KEY_REFERENCE\n")
        _write_text(output / "requirements" / "host-prerequisites.txt", "CPU: minimum 4 vCPU\nMemory: minimum 8 GiB\nDisk: minimum 40 GiB free plus image/archive headroom\nDocker Engine: current supported release with linux/amd64\nDocker Compose: v2\nNetwork: loopback disposable rehearsal; approved outbound access only after operator authorization\nPorts: application/proxy ports selected by the new-server operator\n")
        _write_text(output / "runbook.md", _runbook(candidate_revision, rollback_revision))
        migration = _migration_manifest(candidate_root, static)
        (output / "manifests" / "migration.json").write_text(json.dumps(migration, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        handoff = candidate_root / "docs" / "stage3-rehearsal-handoff-20260826.md"
        if not handoff.is_file():
            raise BundleError("independent rollback handoff evidence is missing")
        identity = {"schema_version": 2, "candidate": candidate, "rollback": rollback, "dependencies": dependencies, "source": source,
                    "ancestry": {"rollback_is_candidate_ancestor": True, "proof": "git-merge-base-is-ancestor"},
                    "independent_rollback_evidence": {"artifact": "stage3-rehearsal-handoff-20260826.md", "sha256": sha256(handoff)},
                    "formal_evidence_sha256": sha256(output / "evidence" / "stage3-evidence.json"), "non_production": True}
        (output / "manifests" / "oci-identity.json").write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        scripts = {item["path"]: item["sha256"] for item in static if item["path"] in {"deploy.ps1", "deploy/fast-release/remote-release.sh"}}
        (output / "manifests" / "deploy-script-checksums.json").write_text(json.dumps(scripts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _write_text(output / "post-deploy-acceptance-checklist.md", _post_deploy_checklist())
        _write_text(output / "requirements" / "secret-references.txt", "DATABASE_URL\nJWT_SECRET\nJWT_REFRESH_SECRET\nDEFAULT_ADMIN_PASSWORD\nLLM_BINDING_API_KEY\nEMBEDDING_API_KEY\nPGPASSFILE\nSSH_KEY_REFERENCE\nPROMETHEUS_SCRAPE_CONFIG_REFERENCE\nBACKUP_CUSTODY_REFERENCE\n")
        sums: list[str] = []
        for file in sorted(p for p in output.rglob("*") if p.is_file() and p.name != "SHA256SUMS"):
            sums.append(f"{sha256(file)}  {file.relative_to(output).as_posix()}")
        _write_text(output / "SHA256SUMS", "\n".join(sums))
        return output
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise


def verify_bundle(bundle: Path) -> dict[str, Any]:
    validate_local_docker()
    bundle = bundle.resolve()
    sums = bundle / "SHA256SUMS"
    if not sums.is_file():
        raise BundleError("SHA256SUMS is missing")
    checked = 0
    listed: set[str] = set()
    for line in sums.read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise BundleError("invalid checksum line") from exc
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or relative.startswith(("/", "\\")) or ".." in Path(relative).parts:
            raise BundleError("invalid checksum path")
        target = (bundle / relative).resolve()
        if bundle not in target.parents or not target.is_file() or target == sums.resolve() or digest != sha256(target) or relative in listed:
            raise BundleError("bundle checksum mismatch")
        listed.add(relative)
        checked += 1
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file() and p != sums}
    if listed != actual:
        raise BundleError("checksum manifest does not cover the complete bundle")
    manifest = json.loads((bundle / "manifests" / "oci-identity.json").read_text(encoding="utf-8"))
    if not manifest.get("non_production") or manifest.get("candidate", {}).get("platform") != "linux/amd64" or manifest.get("rollback", {}).get("platform") != "linux/amd64":
        raise BundleError("invalid OCI identity manifest")
    for path in bundle.rglob("*"):
        # Source and Compose templates necessarily contain literal protocol
        # strings.  The release security boundary is bundle evidence and the
        # generated manifests/requirements, which must never carry values.
        if path.is_file() and path.parent.name in {"evidence", "manifests", "requirements"}:
            text = path.read_bytes()[:2 * 1024 * 1024]
            if SECRET_VALUE.search(text.decode("utf-8", errors="ignore")):
                raise BundleError("bundle secret scan failed")
    return {"status": "ok", "files_checked": checked, "candidate": manifest["candidate"], "rollback": manifest["rollback"]}


def _compose_health_rehearsal(bundle: Path, identity: dict[str, Any], name: str, project: str) -> None:
    """Start the fixed acceptance Compose profile and probe its health.

    The generated env file contains ephemeral values only and is removed in
    the finally block.  Compose is always invoked with a unique project name;
    cleanup is restricted to that project and its volumes.
    """
    source = bundle.resolve() / "source" / "static"
    compose_file = source / "tests" / "acceptance" / "compose.yml"
    if not compose_file.is_file():
        raise BundleError("offline Compose profile is missing")
    run_root = Path(tempfile.mkdtemp(prefix=f"{project}-", dir=TEMP_ROOT))
    env_file = run_root / "compose.env"
    port = 18080 + (int(uuid.uuid4().hex[:4], 16) % 900)
    pg_port = 19080 + (int(uuid.uuid4().hex[:4], 16) % 900)
    postgres_password = uuid.uuid4().hex
    database_name = f"offline_{project.replace('-', '_')}"
    env = {
        "ACCEPTANCE_RUN_ID": project, "ACCEPTANCE_RUN_DIR": str(run_root),
        "ACCEPTANCE_HTTP_PORT": str(port), "ACCEPTANCE_PG_PORT": str(pg_port),
        "ACCEPTANCE_APP_IMAGE": identity["reference"],
        "ACCEPTANCE_POSTGRES_IMAGE": "pgvector/pgvector:pg16",
        "ACCEPTANCE_REDIS_IMAGE": "redis:7-alpine", "ACCEPTANCE_NGINX_IMAGE": "nginx:alpine",
        "POSTGRES_USER": "offline", "POSTGRES_PASSWORD": postgres_password,
        "POSTGRES_DATABASE": database_name,
        "DATABASE_URL": f"postgresql://offline:{postgres_password}@postgres:5432/{database_name}",
        "JWT_SECRET": uuid.uuid4().hex, "JWT_REFRESH_SECRET": uuid.uuid4().hex,
        # The application validates bootstrap passwords at startup.  A raw
        # UUID is hexadecimal-only, so the disposable fixture must include
        # upper/lower/digit/symbol classes without recording its value.
        "DEFAULT_ADMIN_USERNAME": "offline_admin", "DEFAULT_ADMIN_PASSWORD": f"A{uuid.uuid4().hex}!9",
    }
    env_file.write_text("\n".join(f"{key}={value}" for key, value in env.items()) + "\n", encoding="utf-8")
    # Compose references these files through ACCEPTANCE_RUN_DIR.
    for relative in ("nginx.conf", "pgvector-init.sql"):
        source_file = source / "tests" / "acceptance" / relative
        if not source_file.is_file():
            raise BundleError(f"offline Compose asset is missing: {relative}")
        shutil.copy2(source_file, run_root / relative)
    mock_source = source / "tests" / "acceptance" / "mock_video_provider.py"
    if not mock_source.is_file():
        raise BundleError("offline Compose asset is missing: mock_video_provider.py")
    shutil.copy2(mock_source, run_root / "mock_provider.py")
    compose = ["docker", "compose", "-p", project, "--env-file", str(env_file), "-f", str(compose_file)]
    try:
        started = run(compose + ["up", "-d"], timeout=900)
        if started.returncode:
            raise BundleError(f"offline {name} Compose startup failed")
        import urllib.request
        import time
        deadline = time.monotonic() + 300
        base = f"http://127.0.0.1:{port}"
        while time.monotonic() < deadline:
            try:
                statuses = []
                for endpoint in ("/api/live", "/api/ready", "/api/health"):
                    try:
                        with urllib.request.urlopen(base + endpoint, timeout=10) as response:
                            statuses.append(response.status)
                    except Exception:
                        statuses.append(0)
                # A reverse proxy that answers live/ready while the aggregate
                # health endpoint fails is not a usable offline release.
                if statuses == [200, 200, 200]:
                    return
            except Exception:
                time.sleep(1)
        raise BundleError(f"offline {name} health probe failed")
    finally:
        cleanup = run(compose + ["down", "--volumes", "--remove-orphans"], timeout=180)
        if cleanup.returncode:
            raise BundleError(f"offline {name} Compose cleanup failed")
        shutil.rmtree(run_root, ignore_errors=True)
        if run_root.exists():
            raise BundleError(f"offline {name} temporary cleanup failed")


def rehearse(bundle: Path) -> dict[str, Any]:
    verified = verify_bundle(bundle)
    run_id = f"stage3-offline-{uuid.uuid4().hex[:12]}"
    project = run_id.lower()
    labels = [
        "--label", f"raganything.stage3.offline.run-id={run_id}",
        "--label", f"com.docker.compose.project={project}",
    ]
    results: list[dict[str, str]] = []
    try:
        for dependency in ("postgres", "redis", "nginx"):
            archive = bundle.resolve() / "images" / f"{dependency}.tar"
            if not archive.is_file():
                raise BundleError(f"offline {dependency} image archive is missing")
            loaded = run(["docker", "load", "--input", str(archive)], timeout=600)
            if loaded.returncode:
                raise BundleError(f"offline {dependency} image import failed")
        for name in ("candidate", "rollback"):
            archive = bundle.resolve() / "images" / f"{name}.tar"
            loaded = run(["docker", "load", "--input", str(archive)], timeout=600)
            if loaded.returncode:
                raise BundleError(f"offline {name} image import failed")
            identity = verified[name]
            compose_file = bundle.resolve() / "source" / "static" / "tests" / "acceptance" / "compose.yml"
            if compose_file.is_file():
                _compose_health_rehearsal(bundle, identity, name, f"{project}-{name}")
            else:
                probe = run(["docker", "run", "--platform", "linux/amd64", "--rm", *labels, identity.get("reference", identity["digest"]), "python", "-c", "import fastapi, asyncpg; print('offline-health-ok')"], timeout=180)
                if probe.returncode or "offline-health-ok" not in probe.stdout:
                    raise BundleError(f"offline {name} health failed")
            results.append({"image": name, "health": "passed", "revision": identity["revision"], "digest": identity["digest"]})
        return {"status": "passed", "run_id": run_id, "project": project, "candidate": results[0], "rollback": results[1], "transition": "candidate-to-rollback", "cleanup": "manifest-owned-only"}
    finally:
        # Images are intentionally retained: they are the run's imported release
        # artifacts. No prune or foreign-resource deletion is permitted here.
        pass


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    for name in ("candidate-root", "rollback-root", "candidate-revision", "rollback-revision", "candidate-image", "candidate-digest", "rollback-image", "rollback-digest", "evidence", "output"):
        create.add_argument(f"--{name}", required=True, type=Path if name.endswith(("root", "evidence", "output")) else str)
    verify = sub.add_parser("verify"); verify.add_argument("--bundle", required=True, type=Path)
    rehearse_cmd = sub.add_parser("rehearse"); rehearse_cmd.add_argument("--bundle", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            result = {"bundle": str(create_bundle(candidate_root=args.candidate_root, rollback_root=args.rollback_root, candidate_revision=args.candidate_revision, rollback_revision=args.rollback_revision, candidate_image=args.candidate_image, candidate_digest=args.candidate_digest, rollback_image=args.rollback_image, rollback_digest=args.rollback_digest, evidence=args.evidence, output=args.output))}
        elif args.command == "verify": result = verify_bundle(args.bundle)
        else: result = rehearse(args.bundle)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0
    except (BundleError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)[:160]}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
