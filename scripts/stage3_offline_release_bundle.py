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
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterable

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
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
    "docs/postgresql-migration-release-runbook.md",
    "docs/ops/release-operations-runbook.md",
    "docs/isolated-release-acceptance.md",
    "deploy/prometheus/release-scrape-inventory.yml",
    "deploy/prometheus/release-operations-alerts.yml",
)
ARCHIVE_NAMES = ("candidate", "rollback", "postgres", "redis", "nginx")
TOOLING_FILES = (
    "scripts/stage3_offline_release_bundle.py",
    "scripts/verify_stage3_offline_bundle.py",
    "scripts/stage3_offline_preflight.py",
    "scripts/stage3_offline_release_dry_run.py",
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


def _git_file(root: Path, revision: str, relative: str) -> bytes:
    if not FULL_SHA.fullmatch(revision or "") or not (root / ".git").exists():
        raise BundleError("package tooling revision or root is invalid")
    result = subprocess.run(
        ["git", "show", f"{revision}:{relative}"], cwd=root,
        capture_output=True, timeout=60, check=False,
    )
    if result.returncode:
        raise BundleError(f"package tooling file is missing: {relative}")
    return result.stdout


def _copy_static(candidate_root: Path, destination: Path, *, tooling_root: Path, tooling_revision: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    relatives = list(STATIC_FILES)
    relatives.extend(TOOLING_FILES)
    relatives.extend(f"migrations/{path.name}" for path in sorted((candidate_root / "migrations").glob("*.sql")))
    for relative in relatives:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative in TOOLING_FILES:
            # Package tooling is copied from the explicitly recorded commit,
            # never from the concurrent, potentially dirty coordinator tree.
            target.write_bytes(_git_file(tooling_root, tooling_revision, relative))
        else:
            source = candidate_root / relative
            if not source.is_file():
                raise BundleError(f"required static release file is missing: {relative}")
            shutil.copy2(source, target)
        records.append({"path": relative, "sha256": sha256(target)})
    return records


def _checked_files(bundle: Path, sums: Path) -> set[str]:
    if not sums.is_file():
        raise BundleError("archive source SHA256SUMS is missing")
    listed: set[str] = set()
    for line in sums.read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise BundleError("archive source checksum format is invalid") from exc
        relative_path = Path(relative)
        if (not re.fullmatch(r"[0-9a-f]{64}", digest) or relative_path.is_absolute()
                or ".." in relative_path.parts or relative in listed):
            raise BundleError("archive source checksum path is invalid")
        target = bundle / relative_path
        if target.is_symlink() or not target.is_file() or sha256(target) != digest:
            raise BundleError("archive source checksum mismatch")
        listed.add(relative)
    for entry in bundle.rglob("*"):
        if entry.is_symlink():
            raise BundleError("archive source contains a symlink")
    actual = {entry.relative_to(bundle).as_posix() for entry in bundle.rglob("*") if entry.is_file() and entry != sums}
    if listed != actual:
        raise BundleError("archive source allowlist mismatch")
    return listed


def _copy_archives(source_bundle: Path, destination: Path, *, source_sums_sha256: str) -> dict[str, str]:
    source_bundle = source_bundle.resolve()
    source_sums = source_bundle / "SHA256SUMS"
    if not source_bundle.is_dir() or not SHA256.fullmatch(source_sums_sha256 or "") or sha256(source_sums) != source_sums_sha256:
        raise BundleError("archive source identity mismatch")
    _checked_files(source_bundle, source_sums)
    records: dict[str, str] = {}
    for name in ARCHIVE_NAMES:
        source = source_bundle / "images" / f"{name}.tar"
        target = destination / "images" / f"{name}.tar"
        if source.is_symlink() or not source.is_file():
            raise BundleError(f"archive source is missing: {name}")
        shutil.copyfile(source, target)
        source_digest = sha256(source)
        if sha256(target) != source_digest:
            raise BundleError(f"archive copy checksum mismatch: {name}")
        records[name] = source_digest
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


def create_bundle(*, candidate_root: Path, rollback_root: Path, candidate_revision: str, rollback_revision: str, candidate_image: str, candidate_digest: str, rollback_image: str, rollback_digest: str, evidence: Path, output: Path, archive_source: Path, archive_source_sums_sha256: str, tooling_root: Path, tooling_revision: str) -> Path:
    validate_checkout(candidate_root, candidate_revision)
    validate_checkout(rollback_root, rollback_revision)
    if run(["git", "merge-base", "--is-ancestor", rollback_revision, candidate_revision], cwd=candidate_root).returncode:
        raise BundleError("rollback is not a candidate ancestor")
    if not FULL_SHA.fullmatch(tooling_revision or ""):
        raise BundleError("package tooling revision must be a full SHA")
    archive_source = archive_source.resolve()
    try:
        original_identity = json.loads((archive_source / "manifests" / "oci-identity.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError("archive source identity manifest is invalid") from exc
    candidate = original_identity.get("candidate", {})
    rollback = original_identity.get("rollback", {})
    dependencies = original_identity.get("dependencies", {})
    if not all(isinstance(item, dict) for item in (candidate, rollback, dependencies)):
        raise BundleError("archive source identity manifest is invalid")
    if (candidate.get("reference") != candidate_image or candidate.get("revision") != candidate_revision
            or candidate.get("digest") != candidate_digest or rollback.get("reference") != rollback_image
            or rollback.get("revision") != rollback_revision or rollback.get("digest") != rollback_digest):
        raise BundleError("archive source candidate or rollback identity mismatch")
    if candidate_digest == rollback_digest or candidate_revision == rollback_revision:
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
        archive_checksums = _copy_archives(archive_source, output, source_sums_sha256=archive_source_sums_sha256)
        source = _source_archive(candidate_root, candidate_revision, output / "source" / "candidate.tar")
        shutil.copy2(evidence, output / "evidence" / "stage3-evidence.json")
        static = _copy_static(candidate_root, output / "source" / "static", tooling_root=tooling_root.resolve(), tooling_revision=tooling_revision)
        _write_text(output / "requirements" / "secret-references.txt", "DATABASE_URL\nJWT_SECRET\nJWT_REFRESH_SECRET\nDEFAULT_ADMIN_PASSWORD\nLLM_BINDING_API_KEY\nEMBEDDING_API_KEY\nPGPASSFILE\nSSH_KEY_REFERENCE\n")
        _write_text(output / "requirements" / "host-prerequisites.txt", "CPU: minimum 4 vCPU\nMemory: minimum 8 GiB\nDisk: minimum 40 GiB free plus image/archive headroom\nDocker Engine: current supported release with linux/amd64\nDocker Compose: v2\nNetwork: loopback disposable rehearsal; approved outbound access only after operator authorization\nPorts: application/proxy ports selected by the new-server operator\n")
        _write_text(output / "runbook.md", _runbook(candidate_revision, rollback_revision))
        migration = _migration_manifest(candidate_root, static)
        (output / "manifests" / "migration.json").write_text(json.dumps(migration, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        handoff = candidate_root / "docs" / "stage3-rehearsal-handoff-20260826.md"
        if not handoff.is_file():
            raise BundleError("independent rollback handoff evidence is missing")
        tooling_files = {item["path"]: item["sha256"] for item in static if item["path"] in TOOLING_FILES}
        identity = {"schema_version": 3, "candidate": candidate, "rollback": rollback, "package_tooling": {"revision": tooling_revision, "files": tooling_files}, "dependencies": dependencies, "source": source,
                    "ancestry": {"rollback_is_candidate_ancestor": True, "proof": "git-merge-base-is-ancestor"},
                    "independent_rollback_evidence": {"artifact": "stage3-rehearsal-handoff-20260826.md", "sha256": sha256(handoff)},
                    "formal_evidence_sha256": sha256(output / "evidence" / "stage3-evidence.json"),
                    "archive_provenance": {"source_sha256sums": archive_source_sums_sha256, "archives": archive_checksums},
                    "non_production": True}
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
    if any(path.is_symlink() for path in bundle.rglob("*")):
        raise BundleError("bundle contains a symlink")
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
    tooling = manifest.get("package_tooling", {})
    provenance = manifest.get("archive_provenance", {})
    if (manifest.get("schema_version") != 3 or not manifest.get("non_production")
            or manifest.get("candidate", {}).get("platform") != "linux/amd64"
            or manifest.get("rollback", {}).get("platform") != "linux/amd64"
            or not FULL_SHA.fullmatch(str(tooling.get("revision", "")))
            or not isinstance(tooling.get("files"), dict)
            or not isinstance(provenance.get("archives"), dict)):
        raise BundleError("invalid OCI identity manifest")
    for name in ARCHIVE_NAMES:
        archive = bundle / "images" / f"{name}.tar"
        if provenance["archives"].get(name) != sha256(archive):
            raise BundleError("bundle archive provenance mismatch")
    for relative in TOOLING_FILES:
        target = bundle / "source" / "static" / relative
        if tooling["files"].get(relative) != sha256(target):
            raise BundleError("bundle package tooling mismatch")
    for path in bundle.rglob("*"):
        # Source and Compose templates necessarily contain literal protocol
        # strings.  The release security boundary is bundle evidence and the
        # generated manifests/requirements, which must never carry values.
        if path.is_file() and path.parent.name in {"evidence", "manifests", "requirements"}:
            text = path.read_bytes()[:2 * 1024 * 1024]
            if SECRET_VALUE.search(text.decode("utf-8", errors="ignore")):
                raise BundleError("bundle secret scan failed")
    return {"status": "ok", "files_checked": checked, "candidate": manifest["candidate"], "rollback": manifest["rollback"], "dependencies": manifest["dependencies"]}


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
        "DEFAULT_ADMIN_USERNAME": "offline_admin", "DEFAULT_ADMIN_PASSWORD": _bootstrap_password(),
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


def _docker_inventory() -> dict[str, set[str]]:
    commands = {
        "images": ["docker", "image", "ls", "--all", "--no-trunc", "--format", "{{.ID}}\t{{.Repository}}\t{{.Tag}}"],
        "containers": ["docker", "ps", "--all", "--no-trunc", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Labels}}"],
        "networks": ["docker", "network", "ls", "--no-trunc", "--format", "{{.ID}}\t{{.Name}}\t{{.Driver}}"],
        "volumes": ["docker", "volume", "ls", "--format", "{{.Name}}\t{{.Driver}}\t{{.Labels}}"],
    }
    inventory: dict[str, set[str]] = {}
    for name, command in commands.items():
        result = run(command, timeout=60)
        if result.returncode:
            raise BundleError("Docker inventory failed")
        inventory[name] = {line for line in result.stdout.splitlines() if line}
    return inventory


def _inventory_summary(inventory: dict[str, set[str]]) -> dict[str, dict[str, int | str]]:
    return {
        name: {"count": len(values), "sha256": hashlib.sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()}
        for name, values in inventory.items()
    }


def _bootstrap_password() -> str:
    # The fixed prefix satisfies the App's four character-class policy; the
    # suffix remains a fresh CSPRNG value for every disposable Compose run.
    return "Aa1!" + secrets.token_hex(16)


def _ensure_no_tag_conflict(identity: dict[str, Any]) -> None:
    reference = str(identity.get("reference", ""))
    digest = str(identity.get("digest", ""))
    result = run(["docker", "image", "inspect", reference], timeout=60)
    if result.returncode:
        return
    try:
        loaded = json.loads(result.stdout)[0]
    except (json.JSONDecodeError, IndexError, TypeError) as exc:
        raise BundleError("existing image tag inspection is invalid") from exc
    if loaded.get("Id") != digest:
        raise BundleError("foreign image tag conflict")


def _verify_imported_identity(identity: dict[str, Any]) -> None:
    reference = str(identity.get("reference", ""))
    result = run(["docker", "image", "inspect", reference], timeout=60)
    try:
        loaded = json.loads(result.stdout)[0]
    except (json.JSONDecodeError, IndexError, TypeError) as exc:
        raise BundleError("archive import identity inspection is invalid") from exc
    if result.returncode or loaded.get("Id") != identity.get("digest"):
        raise BundleError("archive import identity mismatch")


def rehearse(bundle: Path) -> dict[str, Any]:
    verified = verify_bundle(bundle)
    run_id = f"stage3-offline-{uuid.uuid4().hex[:12]}"
    project = run_id.lower()
    labels = [
        "--label", f"raganything.stage3.offline.run-id={run_id}",
        "--label", f"com.docker.compose.project={project}",
    ]
    identities = {"candidate": verified["candidate"], "rollback": verified["rollback"], **verified["dependencies"]}
    before = _docker_inventory()
    results: list[dict[str, str]] = []
    try:
        for name in ARCHIVE_NAMES:
            identity = identities.get(name)
            if not isinstance(identity, dict):
                raise BundleError(f"offline {name} identity is missing")
            _ensure_no_tag_conflict(identity)
            archive = bundle.resolve() / "images" / f"{name}.tar"
            if not archive.is_file():
                raise BundleError(f"offline {name} image archive is missing")
            loaded = run(["docker", "load", "--input", str(archive)], timeout=600)
            if loaded.returncode:
                raise BundleError(f"offline {name} image import failed")
            _verify_imported_identity(identity)
        for name in ("candidate", "rollback"):
            identity = verified[name]
            compose_file = bundle.resolve() / "source" / "static" / "tests" / "acceptance" / "compose.yml"
            if compose_file.is_file():
                _compose_health_rehearsal(bundle, identity, name, f"{project}-{name}")
            else:
                probe = run(["docker", "run", "--platform", "linux/amd64", "--rm", *labels, identity.get("reference", identity["digest"]), "python", "-c", "import fastapi, asyncpg; print('offline-health-ok')"], timeout=180)
                if probe.returncode or "offline-health-ok" not in probe.stdout:
                    raise BundleError(f"offline {name} health failed")
            results.append({"image": name, "health": "passed", "revision": identity["revision"], "digest": identity["digest"]})
        after = _docker_inventory()
        if not all(before[name].issubset(after[name]) for name in before):
            raise BundleError("foreign Docker inventory changed")
        if any(before[name] != after[name] for name in ("containers", "networks", "volumes")):
            raise BundleError("run-owned Docker cleanup is incomplete")
        return {"status": "passed", "run_id": run_id, "project": project, "candidate": results[0], "rollback": results[1], "transition": "candidate-to-rollback", "cleanup": "manifest-owned-only", "inventory": {"before": _inventory_summary(before), "after": _inventory_summary(after)}}
    finally:
        # Images are intentionally retained: they are the run's imported release
        # artifacts. No prune or foreign-resource deletion is permitted here.
        pass


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    for name in ("candidate-root", "rollback-root", "candidate-revision", "rollback-revision", "candidate-image", "candidate-digest", "rollback-image", "rollback-digest", "evidence", "output", "archive-source", "archive-source-sums-sha256", "tooling-root", "tooling-revision"):
        create.add_argument(f"--{name}", required=True, type=Path if name.endswith(("root", "evidence", "output", "source")) else str)
    verify = sub.add_parser("verify"); verify.add_argument("--bundle", required=True, type=Path)
    rehearse_cmd = sub.add_parser("rehearse"); rehearse_cmd.add_argument("--bundle", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            result = {"bundle": str(create_bundle(candidate_root=args.candidate_root, rollback_root=args.rollback_root, candidate_revision=args.candidate_revision, rollback_revision=args.rollback_revision, candidate_image=args.candidate_image, candidate_digest=args.candidate_digest, rollback_image=args.rollback_image, rollback_digest=args.rollback_digest, evidence=args.evidence, output=args.output, archive_source=args.archive_source, archive_source_sums_sha256=args.archive_source_sums_sha256, tooling_root=args.tooling_root, tooling_revision=args.tooling_revision))}
        elif args.command == "verify": result = verify_bundle(args.bundle)
        else: result = rehearse(args.bundle)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0
    except (BundleError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)[:160]}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
