#!/usr/bin/env python3
"""Fixed, non-production Stage 3 readiness rehearsal coordinator.

This module deliberately has no command-execution arguments.  It binds one
clean detached candidate to local disposable Docker resources and writes only
sanitized evidence.  Production deployment, migration, backup, restore, and
data operations are outside this command's authority: it never invokes
``deploy.ps1`` or ``remote-release.sh``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

try:
    from scripts import release_candidate_inventory
    from scripts.ops import release_ops
except ImportError:  # Direct ``python scripts/...`` execution on Windows.
    import importlib.util

    _SCRIPT_ROOT = Path(__file__).resolve().parent
    _inventory_spec = importlib.util.spec_from_file_location("release_candidate_inventory", _SCRIPT_ROOT / "release_candidate_inventory.py")
    release_candidate_inventory = importlib.util.module_from_spec(_inventory_spec)
    assert _inventory_spec.loader is not None
    _inventory_spec.loader.exec_module(release_candidate_inventory)
    _ops_spec = importlib.util.spec_from_file_location("release_ops", _SCRIPT_ROOT / "ops" / "release_ops.py")
    release_ops = importlib.util.module_from_spec(_ops_spec)
    assert _ops_spec.loader is not None
    _ops_spec.loader.exec_module(release_ops)

SCHEMA_VERSION = 2
RETRYABLE_CLASSES = frozenset({"dependency", "fixture", "launcher", "compose", "browser", "network"})
HARD_STOP_CLASSES = frozenset({"target_identity", "backup_restore", "secret_data_integrity", "image_identity", "rollback"})
STAGE_REGISTRY = ("inventory", "recovery", "acceptance", "rollback")
PRODUCTION_MARKERS = ("production", "prod", "live")
SAFE_TARGET = re.compile(r"^(?:stage3|preprod|staging|acceptance|ci|test)-[a-z0-9][a-z0-9-]{2,63}$")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SENSITIVE_KEY = re.compile(r"password|secret|token|api[_-]?key|dsn|database[_-]?url|authorization|credential", re.I)
PATH_OR_URI = re.compile(r"(?:[a-z][a-z0-9+.-]*://[^\s/'\"]+[^\s]*|[A-Za-z]:[\\/][^\s]*|\\\\[^\s]*|/(?:Users|home|tmp|var|app|workspace)[^\s]*)", re.I)
PRIVATE_IMAGE = re.compile(r"(?:[a-z0-9][a-z0-9.-]*[.:][a-z0-9-]+/)[^\s]+", re.I)


class Stage3Error(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(detail or failure_class)


@dataclass(frozen=True)
class ImageIdentity:
    revision: str
    digest: str
    fingerprint: str


@dataclass
class RepairBudget:
    attempts_per_stage: int = 2
    timeout_seconds: int = 600
    started: float = field(default_factory=time.monotonic)
    repairs: list[dict[str, object]] = field(default_factory=list)

    def can_retry(self, failure_class: str, attempts: int) -> bool:
        return (
            failure_class in RETRYABLE_CLASSES
            # ``attempts`` includes the failed initial execution.  The user
            # budget describes extra repair attempts, so two permits three
            # bounded executions in total.
            and attempts <= self.attempts_per_stage
            and time.monotonic() - self.started < self.timeout_seconds
        )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def sanitize(value: Any, *, key: str = "") -> Any:
    """Return a JSON-safe value without operational identifiers or content."""
    if SENSITIVE_KEY.search(key):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): sanitize(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [sanitize(item, key=key) for item in value]
    if isinstance(value, str):
        text = PATH_OR_URI.sub("<redacted-location>", value)
        text = PRIVATE_IMAGE.sub("<redacted-image>", text)
        return text[:240]
    return value


def _temp_descendant(path: Path) -> Path:
    resolved = path.resolve(strict=False)
    temp_root = Path(tempfile.gettempdir()).resolve()
    if temp_root not in resolved.parents or resolved == temp_root or resolved.is_symlink():
        raise Stage3Error("target_identity", "working directory must be a real system temporary descendant")
    return resolved


def _safe_target(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not SAFE_TARGET.fullmatch(normalized) or any(marker in normalized for marker in PRODUCTION_MARKERS):
        raise Stage3Error("target_identity", "target identifier is not an approved isolated target")
    return normalized


def _safe_database(value: str, *, production_guard: str) -> str:
    database = str(value or "").strip().lower()
    production = str(production_guard or "").strip().lower()
    if not database.startswith("stage3_") or any(marker in database for marker in PRODUCTION_MARKERS):
        raise Stage3Error("target_identity", "isolated database name is not approved")
    if not production or not any(marker in production for marker in PRODUCTION_MARKERS) or database == production:
        raise Stage3Error("target_identity", "production database guard is invalid")
    return database


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if result.returncode:
        raise Stage3Error("target_identity", "candidate git verification failed")
    return result.stdout.strip()


def validate_candidate(candidate_root: Path, commit: str) -> str:
    if not FULL_SHA.fullmatch(commit or ""):
        raise Stage3Error("target_identity", "candidate revision must be a full SHA")
    root = candidate_root.resolve()
    if not (root / ".git").exists():
        raise Stage3Error("target_identity", "candidate root is not a checkout")
    if _git(root, "rev-parse", "HEAD") != commit:
        raise Stage3Error("target_identity", "candidate revision does not match HEAD")
    symbolic = subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    if symbolic.returncode == 0 or _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise Stage3Error("target_identity", "candidate checkout must be clean and detached")
    return commit


def _docker(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)


def validate_local_docker() -> None:
    if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
        raise Stage3Error("target_identity", "remote Docker configuration is forbidden")
    context = _docker(["docker", "context", "show"])
    if context.returncode or context.stdout.strip() != "desktop-linux":
        raise Stage3Error("target_identity", "Docker context must be desktop-linux")


def inspect_image(image: str, expected_revision: str, expected_digest: str) -> ImageIdentity:
    if not image or not DIGEST.fullmatch(expected_digest or ""):
        raise Stage3Error("image_identity", "an expected local image digest is required")
    result = _docker(["docker", "image", "inspect", image, "--format", "{{.Id}}|{{index .Config.Labels \"org.opencontainers.image.revision\"}}"])
    if result.returncode:
        raise Stage3Error("image_identity", "candidate image could not be inspected")
    digest, separator, revision = result.stdout.strip().partition("|")
    if not separator or digest != expected_digest or revision != expected_revision:
        raise Stage3Error("image_identity", "candidate image identity does not match the candidate")
    return ImageIdentity(revision=revision, digest=digest, fingerprint=_hash(f"{revision}:{digest}"))


def _failure_class(exc: Exception) -> str:
    if isinstance(exc, Stage3Error):
        return exc.failure_class
    text = str(exc).lower()
    for name in RETRYABLE_CLASSES:
        if name in text:
            return name
    return "environment_blocked"


def _record_stage(name: str, action: Callable[[], Any], budget: RepairBudget) -> tuple[dict[str, object], bool]:
    attempts = 0
    stage_attempts: list[dict[str, object]] = []
    while True:
        attempts += 1
        started = time.monotonic()
        try:
            value = action()
            stage_attempts.append({"attempt": attempts, "outcome": "passed", "duration_seconds": round(time.monotonic() - started, 3)})
            return {"name": name, "outcome": "passed", "attempts": stage_attempts, "failure_class": "", "detail": sanitize(value)}, True
        except Exception as exc:
            failure_class = _failure_class(exc)
            stage_attempts.append({"attempt": attempts, "outcome": "failed", "duration_seconds": round(time.monotonic() - started, 3), "failure_class": failure_class})
            if failure_class in HARD_STOP_CLASSES:
                return {"name": name, "outcome": "failed", "attempts": stage_attempts, "failure_class": failure_class, "detail": sanitize(str(exc))}, False
            if budget.can_retry(failure_class, attempts):
                repair = {"stage": name, "attempt": attempts, "classification": failure_class, "action": f"retry-{failure_class}"}
                budget.repairs.append(repair)
                continue
            outcome = "environment_blocked" if failure_class == "environment_blocked" else "failed"
            return {"name": name, "outcome": outcome, "attempts": stage_attempts, "failure_class": failure_class, "detail": sanitize(str(exc))}, False


@contextmanager
def _recovery_connection(environment: dict[str, str] | None):
    names = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSFILE")
    previous = {name: os.environ.get(name) for name in names}
    try:
        if environment:
            os.environ.update(environment)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _restore_bundle(
    bundle: Path, confirmation: str, restore_root: Path, isolated_db: str, production_guard: str,
    recovery_environment: dict[str, str] | None = None,
) -> dict[str, object]:
    if bundle is None or not bundle.is_dir():
        raise Stage3Error("backup_restore", "a verified disposable backup bundle is required")
    manifest = release_ops.verify_bundle(bundle)
    if confirmation != manifest.get("backup_id"):
        raise Stage3Error("backup_restore", "backup confirmation does not match verified bundle")
    root = _temp_descendant(restore_root)
    if root.exists() and any(root.iterdir()):
        raise Stage3Error("backup_restore", "restore root must be empty")
    try:
        with _recovery_connection(recovery_environment):
            release_ops.restore_bundle(bundle, root, confirm=confirmation, isolated_pg_database=isolated_db, production_pg_database=production_guard)
    except Exception as exc:
        raise Stage3Error("backup_restore", "isolated backup restore failed") from exc
    # release_ops restores declared asset archives under assets/<asset-id>.
    # The aggregate fixture is intentionally an included run-owned asset, not
    # a loose file written after restore.
    inventory = root / "assets" / "inventory" / "stage3-inventory.json"
    if not inventory.is_file():
        raise Stage3Error("backup_restore", "sanitized restore inventory is missing")
    validation = release_ops.validate_restored_inventory(inventory, root)
    if validation.get("status") != "ok":
        raise Stage3Error("secret_data_integrity", "restored aggregate inventory validation failed")
    return {"backup_fingerprint": _hash(str(manifest["backup_id"])), "artifact_count": len(manifest["artifacts"]), "validation": validation["status"]}


def _rollback_rehearsal(candidate: ImageIdentity, rollback: ImageIdentity) -> dict[str, object]:
    if candidate.digest == rollback.digest or candidate.revision == rollback.revision:
        raise Stage3Error("rollback", "rollback image must be distinct from candidate")
    # The actual Compose driver owns its containers. Stage 3 proves the only
    # permitted rollback pair is distinct and identity-bound; replacement of
    # deployed services is intentionally outside this coordinator.
    return {"rollback_image_fingerprint": rollback.fingerprint, "post_rollback_health": "delegated-to-disposable-driver"}


def _fixed_rollback_runner(
    rollback_root: Path, target_id: str, revision: str, working_dir: Path, image: str, video_fixture: Path,
) -> Callable[[ImageIdentity, ImageIdentity], dict[str, object]]:
    """Re-run the fixed disposable acceptance profile against the rollback image.

    This is deliberately a new Compose project and work directory.  It proves
    rollback runtime health without ever replacing an existing deployment.
    """
    acceptance = _fixed_acceptance_runner(
        rollback_root, target_id, revision, working_dir, image, video_fixture,
    )

    def run(candidate: ImageIdentity, rollback: ImageIdentity) -> dict[str, object]:
        identity = _rollback_rehearsal(candidate, rollback)
        acceptance()
        return identity | {"post_rollback_health": "isolated-preproduction-pass"}

    return run


def _fixed_acceptance_runner(
    candidate_root: Path, target_id: str, commit: str, working_dir: Path, image: str, video_fixture: Path | None,
) -> Callable[[], dict[str, object]]:
    """Return the sole subprocess stage permitted by the coordinator.

    It calls the candidate's checked-in fixed driver, never the caller's
    arbitrary command. Its stdout/stderr are intentionally not evidence.
    """
    if video_fixture is None or not video_fixture.is_absolute() or not video_fixture.is_file():
        raise Stage3Error("fixture", "an absolute disposable video fixture is required by the fixed acceptance driver")
    driver = candidate_root / "scripts" / "run_isolated_acceptance.py"
    if not driver.is_file():
        raise Stage3Error("launcher", "candidate acceptance driver is missing")
    run_dir = working_dir / "fixed-acceptance"

    def run() -> dict[str, object]:
        env = dict(os.environ)
        for name in ("DATABASE_URL", "POSTGRES_PASSWORD", "DEFAULT_ADMIN_PASSWORD", "JWT_SECRET", "JWT_REFRESH_SECRET"):
            env.pop(name, None)
        env["ACCEPTANCE_APP_IMAGE"] = image
        result = subprocess.run(
            [sys.executable, str(driver), "--non-production", "--target-id", f"acceptance-{target_id}", "--commit", commit,
             "--working-dir", str(run_dir), "--video-fixture", str(video_fixture)],
            cwd=candidate_root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=1_200, check=False,
        )
        if result.returncode:
            raise RuntimeError("compose fixed acceptance failed")
        try:
            response = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise RuntimeError("launcher emitted invalid acceptance result") from exc
        if response.get("release_recommendation") != "isolated-preproduction-pass":
            raise RuntimeError("compose fixed acceptance was not releasable")
        return {"recommendation": "isolated-preproduction-pass"}

    return run


def _write_evidence(path: Path, payload: dict[str, object]) -> None:
    safe = sanitize(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(safe, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _best_effort_failure_evidence(working_dir: Path, failure_class: str) -> None:
    """Persist only a stable gate result when the requested directory is safe."""
    try:
        workdir = _temp_descendant(working_dir)
        workdir.mkdir(parents=True, exist_ok=True)
        _write_evidence(workdir / "stage3-evidence.json", {
            "schema_version": SCHEMA_VERSION,
            "non_production": True,
            "release_recommendation": "not-releasable",
            "failure_class": failure_class,
            "stages": [],
            "cleanup": {"outcome": "not-started", "owned_workdir": False},
        })
    except (OSError, Stage3Error):
        # A rejected path must never cause a write outside the temporary root.
        return


def run_rehearsal(
    *, target_id: str, candidate_root: Path, commit: str, working_dir: Path, candidate_image: str,
    candidate_digest: str, rollback_image: str, rollback_digest: str, rollback_revision: str, isolated_database: str,
    production_database_guard: str, backup_bundle: Path | None, backup_confirmation: str, restore_root: Path | None,
    rollback_root: Path | None = None,
    recovery_environment: dict[str, str] | None = None,
    repair_attempts: int = 2, repair_timeout_seconds: int = 600,
    acceptance_runner: Callable[[], dict[str, object]] | None = None,
    recovery_runner: Callable[[], dict[str, object]] | None = None,
    rollback_runner: Callable[[ImageIdentity, ImageIdentity], dict[str, object]] | None = None,
) -> dict[str, object]:
    if not 1 <= repair_attempts <= 2 or not 1 <= repair_timeout_seconds <= 600:
        raise Stage3Error("target_identity", "repair budget can only be tightened from its safe defaults")
    target = _safe_target(target_id)
    workdir = _temp_descendant(working_dir)
    revision = validate_candidate(candidate_root, commit)
    validate_local_docker()
    isolated_db = _safe_database(isolated_database, production_guard=production_database_guard)
    candidate = inspect_image(candidate_image, revision, candidate_digest)
    if not FULL_SHA.fullmatch(rollback_revision or ""):
        raise Stage3Error("image_identity", "rollback revision must be a full SHA")
    rollback = inspect_image(rollback_image, rollback_revision, rollback_digest)
    if candidate.digest == rollback.digest or candidate.revision == rollback.revision:
        raise Stage3Error("image_identity", "candidate and rollback images must differ")
    if rollback_root is not None:
        validate_candidate(rollback_root, rollback_revision)
    workdir.mkdir(parents=True, exist_ok=False)
    evidence_path = workdir / "stage3-evidence.json"
    budget = RepairBudget(repair_attempts, repair_timeout_seconds)
    stages: list[dict[str, object]] = []
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "non_production": True,
        "candidate_revision": revision,
        "candidate_image_fingerprint": candidate.fingerprint,
        "target_fingerprint": _hash(f"{target}:{isolated_db}"),
        "stages": stages,
        "repair_summary": budget.repairs,
        "deferred": ["external-provider", "browser-uat", "production-deployment", "production-migration", "production-data"],
    }
    try:
        stages.append(_record_stage("inventory", lambda: release_candidate_inventory.inventory(candidate_root)["summary"], budget)[0])
        if stages[-1]["outcome"] != "passed":
            return payload
        recovery = recovery_runner or (lambda: _restore_bundle(backup_bundle, backup_confirmation, restore_root, isolated_db, production_database_guard, recovery_environment))
        stages.append(_record_stage("recovery", recovery, budget)[0])
        if stages[-1]["outcome"] != "passed":
            return payload
        if acceptance_runner is None:
            raise Stage3Error("environment_blocked", "fixed acceptance runner was not supplied")
        stages.append(_record_stage("acceptance", acceptance_runner, budget)[0])
        if stages[-1]["outcome"] != "passed":
            return payload
        if rollback_runner is None:
            raise Stage3Error("rollback", "a fixed disposable rollback acceptance runner is required")
        stages.append(_record_stage("rollback", lambda: rollback_runner(candidate, rollback), budget)[0])
        return payload
    finally:
        cleanup_outcome = "passed"
        if restore_root is not None and restore_root.exists():
            try:
                root = _temp_descendant(restore_root)
                if root != workdir:
                    shutil.rmtree(root)
            except (OSError, Stage3Error):
                cleanup_outcome = "failed"
        payload["cleanup"] = {"outcome": "passed", "owned_workdir": True}
        if cleanup_outcome != "passed":
            payload["cleanup"] = {"outcome": "failed", "owned_workdir": True}
        payload["release_recommendation"] = "isolated-stage3-pass" if cleanup_outcome == "passed" and all(stage.get("outcome") == "passed" for stage in stages) else "not-releasable"
        _write_evidence(evidence_path, payload)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--non-production", action="store_true", required=True)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--working-dir", type=Path, required=True)
    parser.add_argument("--candidate-image", required=True)
    parser.add_argument("--candidate-digest", required=True)
    parser.add_argument("--rollback-image", required=True)
    parser.add_argument("--rollback-root", type=Path, required=True)
    parser.add_argument("--rollback-digest", required=True)
    parser.add_argument("--rollback-revision", required=True)
    parser.add_argument("--isolated-database", required=True)
    parser.add_argument("--production-database-guard", required=True)
    parser.add_argument("--backup-bundle", type=Path, required=True)
    parser.add_argument("--backup-confirmation", required=True)
    parser.add_argument("--restore-root", type=Path, required=True)
    parser.add_argument("--recovery-pghost", required=True)
    parser.add_argument("--recovery-pgport", required=True)
    parser.add_argument("--recovery-pguser", required=True)
    parser.add_argument("--recovery-pgpassfile", type=Path, required=True)
    parser.add_argument("--video-fixture", type=Path, required=True)
    parser.add_argument("--repair-attempts", type=int, default=2)
    parser.add_argument("--repair-timeout-seconds", type=int, default=600)
    args = parser.parse_args(argv)
    if not args.non_production:
        return 2
    try:
        # Validate the highest-risk identity before constructing any launcher
        # or touching the candidate checkout.
        _safe_target(args.target_id)
        result = run_rehearsal(
            target_id=args.target_id, candidate_root=args.candidate_root, commit=args.commit, working_dir=args.working_dir,
            candidate_image=args.candidate_image, candidate_digest=args.candidate_digest, rollback_image=args.rollback_image,
            rollback_digest=args.rollback_digest, rollback_revision=args.rollback_revision, isolated_database=args.isolated_database,
            production_database_guard=args.production_database_guard, backup_bundle=args.backup_bundle,
            backup_confirmation=args.backup_confirmation, restore_root=args.restore_root, repair_attempts=args.repair_attempts,
            repair_timeout_seconds=args.repair_timeout_seconds,
            acceptance_runner=_fixed_acceptance_runner(
                args.candidate_root, args.target_id, args.commit, args.working_dir,
                args.candidate_image, args.video_fixture,
            ),
            rollback_root=args.rollback_root,
            recovery_environment={
                "PGHOST": args.recovery_pghost,
                "PGPORT": args.recovery_pgport,
                "PGDATABASE": args.isolated_database,
                "PGUSER": args.recovery_pguser,
                "PGPASSFILE": str(args.recovery_pgpassfile),
            },
            rollback_runner=_fixed_rollback_runner(
                args.rollback_root, f"{args.target_id}-rollback", args.rollback_revision,
                args.working_dir / "fixed-rollback", args.rollback_image, args.video_fixture,
            ),
        )
    except Stage3Error as exc:
        _best_effort_failure_evidence(args.working_dir, exc.failure_class)
        result = {"schema_version": SCHEMA_VERSION, "release_recommendation": "not-releasable", "failure_class": exc.failure_class}
    print(json.dumps(sanitize(result), ensure_ascii=True, sort_keys=True))
    return 0 if result.get("release_recommendation") == "isolated-stage3-pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
