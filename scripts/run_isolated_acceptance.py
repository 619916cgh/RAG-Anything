#!/usr/bin/env python3
"""Run the fixed disposable Compose acceptance profile.

This command owns the Compose project, credentials, temporary files, and cleanup.
It never accepts arbitrary stage commands and never reads the repository .env.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import concurrent.futures
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "tests" / "acceptance" / "compose.yml"
ISOLATED_MARKERS = ("staging", "preprod", "acceptance", "ci", "test", "uat")
UNSAFE_MARKERS = ("production", "live")
_EXPLICIT_ISOLATED_TARGETS = {"video-semantic-segment-index"}
_LOCAL_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\|file://|/(?:app|tmp|var|home|Users|uploads)(?:[\\/]|$))",
    re.IGNORECASE,
)
_OWNER_LABEL = "raganything.acceptance.owner"
_RUN_LABEL = "raganything.acceptance.run-id"
_ACCEPTANCE_OWNER = "video-semantic-segment-index-full-uat"
_BEHAVIOR_SHA = "ac5a35cac6de33747755bac1b8fa3c4b3ebdbab2"
_VERIFICATION_SOURCE_SHA = "3dd1bc14194b0348fb3ad1ed51b536085fa6b2c8"
_INITIAL_VERIFICATION_SHA = "e1739d48b77a309552eb1f5f55d8ad27a204beed"
_INITIAL_VERIFICATION_PATHS = {
    "scripts/run_isolated_acceptance.py",
    "tests/acceptance/compose.yml",
    "tests/acceptance/generate_video_fixture.py",
    "tests/acceptance/video_browser_uat.mjs",
    "tests/test_video_acceptance_contract.py",
    "handoff-video54-sse-body-ownership-20260901.md",
    "handoff-video54-sse-manifest-repair-20260901.md",
    "summary-delta-video54-sse-body-ownership-20260901.md",
    "summary-delta-video54-sse-manifest-repair-20260901.md",
}
_VERIFICATION_PATHS = _INITIAL_VERIFICATION_PATHS | {
    "Dockerfile",
    "scripts/run_isolated_acceptance.py",
    "tests/acceptance/compose.yml",
    "tests/acceptance/generate_compat_fixtures.py",
    "tests/acceptance/generate_video_fixture.py",
    "tests/acceptance/test_video_worker_sse.py",
    "tests/acceptance/prepare_video_citation_probe.py",
    "handoff-video54-sse-body-ownership-20260901.md",
    "handoff-video54-sse-manifest-repair-20260901.md",
    "handoff-video54-browser-render-manifest-repair-20260902.md",
    "handoff-video54-browser-full-evidence-20260902.md",
    "handoff-video54-browser-parallel-diagnosis-20260902.md",
    "summary-delta-video54-sse-body-ownership-20260901.md",
    "summary-delta-video54-sse-manifest-repair-20260901.md",
    "summary-delta-video54-browser-render-manifest-repair-20260902.md",
    "summary-delta-video54-browser-full-evidence-20260902.md",
    "summary-delta-video54-browser-parallel-diagnosis-20260902.md",
}
_FIXTURE_STAGE_NAMES = (
    "fixture-create",
    "mount-path",
    "ffmpeg-encode",
    "file-exists/nonempty",
    "ffprobe-probe",
    "compatibility-fixture",
    "readiness",
)
_NAVIGATION_PROBE_PHASES = {
    "goto_started", "goto_completed", "detail_wait_started", "detail_response_status",
    "page_ready", "sidebar_locator_count", "main_conversation_locator_count",
    "target_thread_locator_count", "active_thread_match", "decoy_locator_count",
    "target_click_started", "target_click_completed", "stale_state_assertion",
    "reload_started", "reload_completed", "timeout_stage", "failure_class",
}
_CITATION_PROBE_PHASES = {
    "query_submit_started", "query_submit_completed", "target_query_identity_observed",
    "response_wait_started", "response_received", "response_status", "response_content_type",
    "body_read_started", "body_read_completed", "body_read_error_class", "body_byte_count",
    "request_finished", "request_failed", "done_received", "done_thread_matches_target", "done_citation_count",
    "response_body_read_started", "response_body_read_completed", "response_body_byte_count",
    "sse_event_framing", "sse_line_count", "sse_data_line_count", "sse_json_parse_error_count",
    "stream_response_started", "stream_response_completed", "sse_done_received",
    "sse_done_thread_matches_target", "sse_done_citation_count", "streaming_assistant_found",
    "streaming_citation_found", "streaming_video_player_found", "player_visible",
    "persisted_conversation_get", "persisted_assistant_found", "persisted_video_segments_found",
    "reload_started", "reload_completed", "reloaded_player_visible",
    "authorized_media_status", "range_status", "timeout_stage", "failure_class",
}
_CITATION_ARRAY_SHAPES = {"absent", "non_array", "array"}
_RETRIEVAL_CONTEXT_SHAPES = {"absent", "string", "array", "object", "unknown"}
_RETRIEVAL_ANCHOR_DETECTIONS = {"matched", "not_matched", "unavailable"}
_CITATION_VIDEO_SEGMENT_SHAPES = {"absent", "object", "array", "unknown"}
_SAFE_FAILURE_PATH = re.compile(r"^/api/agents/:agent/query/stream$")
_CITATION_FAILURE_CLASSES = {
    "response_wait_timeout",
    "sse_body_read_failure",
    "sse_event_parse_failure",
    "sse_json_parse_failure",
    "sse_contract_mismatch",
    "sse_done_missing",
    "sse_done_thread_mismatch",
    "sse_done_citations_missing",
}


class StageFailure(RuntimeError):
    def __init__(self, failure_class: str):
        super().__init__(failure_class)
        self.failure_class = failure_class


def _safe_target(value: str) -> str:
    value = str(value or "").strip().lower()
    if not value or any(marker in value for marker in UNSAFE_MARKERS) or (
        value not in _EXPLICIT_ISOLATED_TARGETS and not any(marker in value for marker in ISOLATED_MARKERS)
    ):
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


def _write_redacted_command_output(path: Path, result: subprocess.CompletedProcess[str], *, label: str) -> None:
    """Export bounded command diagnostics without retaining bodies or credentials."""
    text = "\n".join((result.stdout or "", result.stderr or ""))
    text = re.sub(r"https?://[^\s'\"<>]+", "[url]", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:postgres(?:ql)?://|redis://)[^\s'\"<>]+", "[dsn]", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", r"\1 [redacted]", text, flags=re.IGNORECASE)
    text = re.sub(r"(?i)(password|token|secret|authorization|cookie)\s*[=:]\s*[^\s,;]+", r"\1=[redacted]", text)
    text = re.sub(r"(?i)data:\s*\{.*", "data: [redacted]", text)
    text = re.sub(r"(?i)(?:[A-Za-z]:[\\/]|/(?:acceptance|app|tmp|var|home|Users)(?:[\\/]))[^\s'\"<>]+", "[path]", text)
    lines = [line.replace("\r", "")[:320] for line in text.splitlines()[:128]]
    path.write_text(json.dumps({"label": label, "returncode": int(result.returncode), "lines": lines}, ensure_ascii=True, sort_keys=True), encoding="utf-8")


def _write_diagnosis_command_output(path: Path, result: subprocess.CompletedProcess[str], *, label: str) -> None:
    text = "\n".join((result.stdout or "", result.stderr or "")).lower()
    categories = {
        "worker": sum(text.count(token) for token in ("worker", "processing task")),
        "video": sum(text.count(token) for token in ("video", "ffmpeg", "ffprobe")),
        "provider": sum(text.count(token) for token in ("provider", "embedding", "model")),
        "error": sum(text.count(token) for token in ("error", "failed", "exception")),
    }
    path.write_text(json.dumps({"label": label, "returncode": int(result.returncode), "category_counts": {key: min(999, value) for key, value in categories.items()}}, ensure_ascii=True, sort_keys=True), encoding="utf-8")


def _require_local_docker(env: dict[str, str]) -> None:
    if env.get("DOCKER_HOST") or env.get("DOCKER_CONTEXT"):
        raise ValueError("DOCKER_HOST and DOCKER_CONTEXT must be unset for local acceptance")
    context = _run(["docker", "context", "show"], env=env, timeout=20).stdout.strip()
    if context != "desktop-linux":
        raise ValueError("Docker context must be desktop-linux")


def _require_isolated_venv() -> None:
    """Require an explicit virtual environment without constraining its checkout."""
    executable = Path(os.path.realpath(sys.executable))
    prefix = Path(os.path.realpath(sys.prefix))
    base_prefix = Path(os.path.realpath(getattr(sys, "base_prefix", sys.prefix)))
    if prefix == base_prefix:
        raise ValueError("acceptance runner requires a virtual environment")
    if executable.parent != prefix and prefix not in executable.parents:
        raise ValueError("acceptance runner interpreter does not belong to its venv")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verification_identity(revision: str, env: dict[str, str]) -> dict[str, object]:
    """Bind evidence to the approved behavior baseline and verification-only diff."""
    behavior_base = _run(["git", "merge-base", _BEHAVIOR_SHA, revision], env=env, timeout=20).stdout.strip()
    source_base = _run(["git", "merge-base", _VERIFICATION_SOURCE_SHA, revision], env=env, timeout=20).stdout.strip()
    initial_paths = set(_run(["git", "diff", "--name-only", f"{_BEHAVIOR_SHA}..{_INITIAL_VERIFICATION_SHA}"], env=env, timeout=20).stdout.splitlines())
    changed_paths = set(_run(["git", "diff", "--name-only", f"{_BEHAVIOR_SHA}..{revision}"], env=env, timeout=20).stdout.splitlines())
    if behavior_base != _BEHAVIOR_SHA or initial_paths != _INITIAL_VERIFICATION_PATHS or not changed_paths <= _VERIFICATION_PATHS:
        raise ValueError("verification ancestry or diff scope is invalid")
    return {
        "behavior_sha": _BEHAVIOR_SHA,
        "verification_sha": revision,
        "verification_source_sha": _VERIFICATION_SOURCE_SHA,
        "behavior_merge_base": behavior_base,
        "verification_source_merge_base": source_base,
        "initial_verification_diff": sorted(initial_paths),
        "final_verification_diff": sorted(changed_paths),
    }


def _docker_inventory(env: dict[str, str]) -> dict[str, dict[str, object]]:
    commands = {
        "containers": ["docker", "ps", "-a", "--format", "{{.Names}}"],
        "networks": ["docker", "network", "ls", "--format", "{{.Name}}"],
        "volumes": ["docker", "volume", "ls", "--format", "{{.Name}}"],
    }
    inventory: dict[str, dict[str, object]] = {}
    for kind, command in commands.items():
        result = _run(command, env=env, timeout=20)
        if result.returncode:
            raise RuntimeError("foreign-docker-inventory")
        names = sorted({value for value in result.stdout.splitlines() if value})
        inventory[kind] = {"count": len(names), "names": names}
    return inventory


def _docker_inventory_summary(inventory: dict[str, dict[str, object]]) -> dict[str, dict[str, int]]:
    """Keep foreign inventory names in memory while evidence records counts only."""
    summary: dict[str, dict[str, int]] = {}
    for kind in ("containers", "networks", "volumes"):
        entry = inventory.get(kind)
        if not isinstance(entry, dict) or not isinstance(entry.get("count"), int):
            raise ValueError("foreign Docker inventory is invalid")
        summary[kind] = {"count": entry["count"]}
    return summary


def _load_build_metadata(path_value: str) -> tuple[str, str | None]:
    path = Path(path_value).resolve()
    if not path.is_file() or path.stat().st_size > 16 * 1024:
        raise ValueError("acceptance image build metadata is unavailable")
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
        manifest_digest = str(metadata["containerimage.digest"])
        config_digest_value = metadata.get("containerimage.config.digest")
        config_digest = str(config_digest_value) if config_digest_value else None
    except (KeyError, OSError, TypeError, ValueError):
        raise ValueError("acceptance image build metadata is invalid") from None
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", manifest_digest):
        raise ValueError("acceptance image build metadata digests are invalid")
    if config_digest is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", config_digest):
        raise ValueError("acceptance image build metadata digests are invalid")
    return manifest_digest, config_digest


def _require_image_revision(image: str, commit: str, metadata_path: str, env: dict[str, str]) -> dict[str, str]:
    expected_digest, expected_config_digest = _load_build_metadata(metadata_path)
    inspected = _run(["docker", "image", "inspect", image], env=env, timeout=20)
    if inspected.returncode:
        raise ValueError("acceptance app image is unavailable")
    try:
        data = json.loads(inspected.stdout)[0]
        labels = (data.get("Config") or {}).get("Labels") or {}
        repo_digests = [str(value) for value in data.get("RepoDigests") or []]
        image_id = str(data.get("Id") or "")
        platform = f"{data.get('Os', '')}/{data.get('Architecture', '')}"
    except (IndexError, TypeError, ValueError):
        raise ValueError("acceptance app image identity is invalid") from None
    if labels.get("org.opencontainers.image.revision") != commit:
        raise ValueError("acceptance app image is missing the requested commit revision label")
    if platform != "linux/amd64" or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_digest):
        raise ValueError("acceptance app image platform or OCI manifest digest is invalid")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise ValueError("acceptance app image ID is invalid")
    if repo_digests:
        if not any(item.endswith(f"@{expected_digest}") for item in repo_digests):
            raise ValueError("acceptance app image manifest digest does not match its repository digest")
        identity_evidence = "repository-digest"
    else:
        # Drivers may expose either a config digest or only the local OCI
        # manifest digest. In both forms the revision label and image ID bind
        # the loaded image to BuildKit metadata without a registry lookup.
        expected_local_id = expected_config_digest or expected_digest
        if image_id != expected_local_id:
            raise ValueError("acceptance app image local identity does not match build metadata")
        identity_evidence = "build-metadata-local-config"
    return {"tag": image, "revision": commit, "platform": platform, "oci_manifest_digest": expected_digest, "config_digest": expected_config_digest, "image_id": image_id, "identity_evidence": identity_evidence}


def _owned_resources(project: str, run_id: str, env: dict[str, str]) -> dict[str, list[str]]:
    """Discover only resources carrying both this run's labels."""
    filters = ["--filter", f"label={_RUN_LABEL}={run_id}", "--filter", f"label={_OWNER_LABEL}={_ACCEPTANCE_OWNER}"]
    commands = {
        "containers": ["docker", "ps", "-aq", *filters],
        "volumes": ["docker", "volume", "ls", "-q", *filters],
        "networks": ["docker", "network", "ls", "-q", *filters],
    }
    resources: dict[str, list[str]] = {}
    for kind, command in commands.items():
        result = _run(command, env=env, timeout=20)
        if result.returncode:
            raise RuntimeError("owned-resource-inventory")
        resources[kind] = [item for item in result.stdout.splitlines() if item]
    for kind, values in resources.items():
        for value in values:
            inspect = _run(["docker", kind[:-1], "inspect", value], env=env, timeout=20)
            if inspect.returncode:
                raise RuntimeError("owned-resource-inspect")
            try:
                data = json.loads(inspect.stdout)[0]
                labels = data.get("Config", {}).get("Labels", {}) if kind == "containers" else data.get("Labels", {})
            except (IndexError, TypeError, ValueError):
                raise RuntimeError("owned-resource-labels") from None
            if labels.get(_RUN_LABEL) != run_id or labels.get(_OWNER_LABEL) != _ACCEPTANCE_OWNER:
                raise RuntimeError("owned-resource-labels")
            if labels.get("com.docker.compose.project") != project:
                raise RuntimeError("owned-resource-project")
    return resources


def _record_resource_lifecycle(manifest: dict[str, object], env: dict[str, str]) -> None:
    """Record only run-labelled resource identifiers and their final cleanup state."""
    run_id = str(manifest.get("run_id") or "")
    project = str(manifest.get("project") or "")
    expected = manifest.get("resources")
    if not run_id or not project or not isinstance(expected, dict):
        raise RuntimeError("resource-lifecycle-manifest")
    remaining = _owned_resources(project, run_id, env)
    created = {kind: sorted(map(str, expected.get(kind, []))) for kind in remaining}
    if any(sorted(remaining[kind]) != created[kind] for kind in remaining):
        raise RuntimeError("resource-lifecycle-ownership-mismatch")
    manifest["resource_lifecycle"] = {
        kind: {
            "created": created[kind],
            "removed": [],
            "remaining": created[kind],
            "status_confirmed": True,
        }
        for kind in created
    }


def _reconcile_resource_lifecycle(manifest: dict[str, object], env: dict[str, str]) -> None:
    """Refresh ownership after one-shot stages while retaining prior evidence."""
    resources = manifest.get("resources")
    lifecycle = manifest.get("resource_lifecycle")
    if not isinstance(resources, dict) or not isinstance(lifecycle, dict):
        raise RuntimeError("resource-lifecycle-manifest")
    current = _owned_resources(str(manifest.get("project") or ""), str(manifest.get("run_id") or ""), env)
    for kind in ("containers", "volumes", "networks"):
        entry = lifecycle.setdefault(kind, {"created": [], "removed": [], "remaining": [], "status_confirmed": False})
        if not isinstance(entry, dict):
            raise RuntimeError("resource-lifecycle-invalid")
        created = sorted(set(map(str, entry.get("created", []))) | set(map(str, resources.get(kind, []))) | set(map(str, current.get(kind, []))))
        remaining = sorted(map(str, current.get(kind, [])))
        entry["created"] = created
        entry["remaining"] = remaining
        entry["removed"] = [value for value in created if value not in remaining]
        entry["status_confirmed"] = True
    manifest["resources"] = {kind: sorted(map(str, current.get(kind, []))) for kind in ("containers", "volumes", "networks")}


def _finalize_resource_lifecycle(manifest: dict[str, object], env: dict[str, str]) -> None:
    """Reconcile removal evidence after cleanup without inventing missing state."""
    lifecycle = manifest.get("resource_lifecycle")
    if not isinstance(lifecycle, dict):
        raise RuntimeError("resource-lifecycle-missing")
    run_id = str(manifest.get("run_id") or "")
    project = str(manifest.get("project") or "")
    remaining = _owned_resources(project, run_id, env)
    for kind, values in remaining.items():
        entry = lifecycle.get(kind)
        if not isinstance(entry, dict) or not isinstance(entry.get("created"), list):
            raise RuntimeError("resource-lifecycle-invalid")
        created = sorted(map(str, entry["created"]))
        current = sorted(values)
        if not set(current) <= set(created):
            raise RuntimeError("resource-lifecycle-ownership-mismatch")
        entry["remaining"] = current
        entry["removed"] = [value for value in created if value not in current]
        entry["status_confirmed"] = True


def _load_citation_probe_lifecycle(path: Path, *, run_id: str, owner: str, project: str) -> dict[str, bool]:
    """Read the bounded Browser lifecycle from either a passed or failed probe."""
    if not path.is_file() or path.stat().st_size > 32 * 1024:
        raise ValueError("citation probe lifecycle evidence is missing or oversized")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        raise ValueError("citation probe lifecycle evidence is invalid") from None
    if not isinstance(payload, dict) or payload.get("schema_version") != 3 or payload.get("browser") != "playwright" or payload.get("browser_citation_only") is not True:
        raise ValueError("citation probe lifecycle evidence schema is invalid")
    if payload.get("run_id") != run_id or payload.get("owner") != owner or payload.get("compose_project") != project:
        raise ValueError("citation probe lifecycle evidence identity is invalid")
    profile = payload.get("browser_profile")
    fixture = payload.get("browser_fixture")
    if not isinstance(profile, dict) or set(profile) != {"created", "used", "context_closed", "cleaned"} or any(not isinstance(profile[key], bool) for key in profile):
        raise ValueError("citation probe lifecycle profile is invalid")
    if not isinstance(fixture, dict) or set(fixture) != {"owned_by_run", "created"} or fixture.get("owned_by_run") is not True or not isinstance(fixture.get("created"), bool):
        raise ValueError("citation probe lifecycle fixture is invalid")
    return dict(profile)


def _cleanup_owned(manifest: dict[str, object], env: dict[str, str]) -> None:
    run_id = str(manifest.get("run_id") or "")
    project = str(manifest.get("project") or "")
    expected = manifest.get("resources")
    if not run_id or not project or not isinstance(expected, dict):
        raise RuntimeError("cleanup-manifest")
    current = _owned_resources(project, run_id, env)
    normalized = {kind: sorted(map(str, expected.get(kind, []))) for kind in current}
    if {kind: sorted(values) for kind, values in current.items()} != normalized:
        raise RuntimeError("cleanup-ownership-mismatch")
    for container in current["containers"]:
        if _run(["docker", "container", "rm", "-f", container], env=env, timeout=60).returncode:
            raise RuntimeError("cleanup-container")
    for volume in current["volumes"]:
        if _run(["docker", "volume", "rm", volume], env=env, timeout=60).returncode:
            raise RuntimeError("cleanup-volume")
    for network in current["networks"]:
        if _run(["docker", "network", "rm", network], env=env, timeout=60).returncode:
            raise RuntimeError("cleanup-network")
    if any(_owned_resources(project, run_id, env).values()):
        raise RuntimeError("cleanup-owned-resources-remain")


def _cleanup_owned_browser_profile(manifest: dict[str, object], workdir: Path) -> None:
    artifacts = manifest.get("artifacts")
    profile_name = artifacts.get("browser_profile") if isinstance(artifacts, dict) else None
    if profile_name != "browser-profile":
        raise RuntimeError("cleanup-browser-profile-manifest")
    profile = (workdir / profile_name).resolve()
    if profile.parent != workdir.resolve():
        raise RuntimeError("cleanup-browser-profile-path")
    if profile.exists():
        shutil.rmtree(profile)
    if profile.exists():
        raise RuntimeError("cleanup-browser-profile-remains")


def _stage(name: str, fn, evidence: list[dict[str, object]]) -> bool:
    started = time.monotonic()
    try:
        detail = fn()
        ok = True
    except Exception as exc:  # evidence deliberately stores only a bounded class
        detail = getattr(exc, "failure_class", type(exc).__name__)
        ok = False
    evidence.append({"name": name, "outcome": "passed" if ok else "failed", "duration_seconds": round(time.monotonic() - started, 3), "detail": "" if ok else str(detail)[:160]})
    return ok


def _classify_pytest_failure(result: subprocess.CompletedProcess[str]) -> str:
    """Keep acceptance evidence useful without retaining pytest output."""
    output = f"{result.stdout}\n{result.stderr}".lower()
    if "modulenotfounderror" in output or "importerror" in output:
        return "missing-module"
    if "undefinedtable" in output or "undefinedcolumn" in output or "does not exist" in output:
        return "database-schema"
    if "connection refused" in output or "cannot connect" in output or "database_url" in output:
        return "database-connection"
    if "asyncpg" in output or "postgres" in output or "database" in output:
        return "database-runtime"
    if "timeout" in output:
        return "timeout"
    if "assertionerror" in output or "assert " in output:
        return "assertion"
    return "unknown"


def _wait_for_health(base: str, *, timeout: int = 90) -> None:
    """Wait for the composed migration, application, and proxy chain."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            for path in ("/api/live", "/api/ready", "/api/health"):
                with urllib.request.urlopen(base + path, timeout=10) as response:
                    if response.status != 200:
                        raise RuntimeError("health status is not ready")
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("health check timed out")


def _stage_video_fixture(source: Path, workdir: Path) -> Path:
    if not source.is_absolute() or not source.is_file() or source.suffix.lower() not in {".mp4", ".m4v", ".mov"}:
        raise ValueError("--video-fixture must be an absolute existing MP4-family file")
    if source.stat().st_size <= 0:
        raise ValueError("--video-fixture must not be empty")
    target = workdir / f"video-fixture{source.suffix.lower()}"
    shutil.copy2(source, target)
    return target


def _database_test_environments(
    compose_env: dict[str, str], *, password: str, pg_port: str
) -> tuple[dict[str, str], dict[str, str]]:
    """Keep the migrated application DB separate from the migration admin DB."""
    parsed = urlsplit(compose_env["DATABASE_URL"])
    application_database_url = urlunsplit(
        (parsed.scheme, f"acceptance:{password}@127.0.0.1:{pg_port}", parsed.path, parsed.query, parsed.fragment)
    )
    migration_admin_database_url = urlunsplit(
        (parsed.scheme, f"acceptance:{password}@127.0.0.1:{pg_port}", "/postgres", parsed.query, parsed.fragment)
    )
    if application_database_url == migration_admin_database_url:
        raise RuntimeError("acceptance-database-url-alias")
    application_env = dict(compose_env)
    application_env["DATABASE_URL"] = application_database_url
    migration_env = dict(application_env)
    migration_env["MIGRATION_TEST_DATABASE_URL"] = migration_admin_database_url
    return application_env, migration_env


_FIXTURE_FAILURE_CLASSES = {
    "", "fixture-preexisting", "mount-path-invalid", "command-not-found",
    "command-failed", "fixture-missing", "probe-invalid",
    "compatibility-source-missing", "fixture-incomplete", "fixture-invalid",
}
_ELAPSED_BUCKETS = {"lt_1s", "lt_5s", "lt_30s", "gte_30s"}


def _load_fixture_stage_evidence(path: Path, *, run_id: str, owner: str, service_exit_code: int) -> dict[str, object]:
    """Accept only the small, path-free fixture launcher evidence schema."""
    if not path.is_file() or path.stat().st_size > 16 * 1024:
        raise StageFailure("fixture-evidence-unavailable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        stages = payload["stages"]
    except (KeyError, OSError, TypeError, ValueError):
        raise StageFailure("fixture-evidence-invalid") from None
    if payload.get("schema_version") == 1 and payload.get("owned_by_run") is True:
        normalized_stages: list[dict[str, object]] = []
        for stage in stages if isinstance(stages, list) else []:
            if not isinstance(stage, dict):
                raise StageFailure("fixture-evidence-invalid")
            duration = stage.get("duration_seconds")
            if not isinstance(duration, (int, float)) or duration < 0:
                raise StageFailure("fixture-evidence-invalid")
            elapsed_bucket = "lt_1s" if duration < 1 else "lt_5s" if duration < 5 else "lt_30s" if duration < 30 else "gte_30s"
            normalized_stages.append({
                "name": stage.get("name"),
                "outcome": stage.get("outcome"),
                "exit_code": stage.get("exit_code"),
                "elapsed_bucket": elapsed_bucket,
                "failure_class": stage.get("failure_class"),
            })
        failed = next((stage for stage in normalized_stages if stage.get("outcome") == "failed"), None)
        source = path.parent / "generate_compat_fixtures.py"
        video = path.parent / "video-fixture.mp4"
        source_exists = source.is_file()
        source_nonempty = source_exists and source.stat().st_size > 0
        failure_stage = str(failed.get("name", "")) if failed else ""
        failure_class = str(failed.get("failure_class", "")) if failed else ""
        if failure_stage == "compatibility-fixture" and not source_nonempty:
            failure_class = "compatibility-source-missing"
        payload = {
            "schema_version": 2,
            "owned_by_run": True,
            "run_id": run_id,
            "owner": owner,
            "source_exists": source_exists,
            "source_nonempty": source_nonempty,
            "ffmpeg_started": any(stage.get("name") == "ffmpeg-encode" for stage in normalized_stages),
            "ffmpeg_exit_code": next((stage.get("exit_code") for stage in normalized_stages if stage.get("name") == "ffmpeg-encode"), None),
            "ffprobe_started": any(stage.get("name") == "ffprobe-probe" for stage in normalized_stages),
            "ffprobe_exit_code": next((stage.get("exit_code") for stage in normalized_stages if stage.get("name") == "ffprobe-probe"), None),
            "generated_mp4_exists": video.is_file(),
            "generated_mp4_nonempty": video.is_file() and video.stat().st_size > 0,
            "compatibility_txt_generated": (path.parent / "compatibility.txt").is_file() and (path.parent / "compatibility.txt").stat().st_size > 0,
            "compatibility_png_generated": (path.parent / "compatibility.png").is_file() and (path.parent / "compatibility.png").stat().st_size > 0,
            "compatibility_pdf_generated": (path.parent / "compatibility.pdf").is_file() and (path.parent / "compatibility.pdf").stat().st_size > 0,
            "output_mount_visible": True,
            "compatibility_validation_passed": all((path.parent / name).is_file() and (path.parent / name).stat().st_size > 0 for name in ("compatibility.txt", "compatibility.png", "compatibility.pdf")),
            "fixture_service_exit_code": service_exit_code,
            "fixture_failure_stage": failure_stage,
            "failure_class": failure_class,
            "stages": normalized_stages,
        }
        stages = payload["stages"]
    expected_keys = {
        "schema_version", "owned_by_run", "run_id", "owner", "source_exists", "source_nonempty",
        "ffmpeg_started", "ffmpeg_exit_code", "ffprobe_started", "ffprobe_exit_code",
        "generated_mp4_exists", "generated_mp4_nonempty", "compatibility_txt_generated",
        "compatibility_png_generated", "compatibility_pdf_generated", "output_mount_visible",
        "compatibility_validation_passed", "fixture_service_exit_code", "fixture_failure_stage",
        "failure_class", "stages",
    }
    if set(payload) != expected_keys or payload.get("schema_version") != 2 or payload.get("owned_by_run") is not True or payload.get("run_id") != run_id or payload.get("owner") != owner or not isinstance(stages, list) or not stages:
        raise StageFailure("fixture-evidence-invalid")
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    if _LOCAL_PATH_RE.search(serialized):
        raise StageFailure("fixture-evidence-invalid")
    bool_fields = (
        "source_exists", "source_nonempty", "ffmpeg_started", "ffprobe_started",
        "generated_mp4_exists", "generated_mp4_nonempty", "compatibility_txt_generated",
        "compatibility_png_generated", "compatibility_pdf_generated", "output_mount_visible",
        "compatibility_validation_passed",
    )
    if any(not isinstance(payload[field], bool) for field in bool_fields):
        raise StageFailure("fixture-evidence-invalid")
    for started_key, exit_key in (("ffmpeg_started", "ffmpeg_exit_code"), ("ffprobe_started", "ffprobe_exit_code")):
        value = payload[exit_key]
        if (payload[started_key] and (not isinstance(value, int) or not 0 <= value <= 255)) or (not payload[started_key] and value is not None):
            raise StageFailure("fixture-evidence-invalid")
    service_exit = payload["fixture_service_exit_code"]
    failure_stage = payload["fixture_failure_stage"]
    failure_class = payload["failure_class"]
    if not isinstance(service_exit, int) or not 0 <= service_exit <= 255 or not isinstance(failure_stage, str) or (failure_stage and failure_stage not in _FIXTURE_STAGE_NAMES) or not isinstance(failure_class, str) or failure_class not in _FIXTURE_FAILURE_CLASSES:
        raise StageFailure("fixture-evidence-invalid")
    names: list[str] = []
    for stage in stages:
        if not isinstance(stage, dict) or set(stage) != {"name", "outcome", "exit_code", "elapsed_bucket", "failure_class"}:
            raise StageFailure("fixture-evidence-invalid")
        name, outcome, exit_code = stage["name"], stage["outcome"], stage["exit_code"]
        elapsed_bucket, stage_failure = stage["elapsed_bucket"], stage["failure_class"]
        if not isinstance(name, str) or not isinstance(outcome, str) or not isinstance(exit_code, int) or not isinstance(elapsed_bucket, str) or not isinstance(stage_failure, str):
            raise StageFailure("fixture-evidence-invalid")
        if name not in _FIXTURE_STAGE_NAMES or outcome not in {"passed", "failed"} or exit_code < 0 or exit_code > 255 or elapsed_bucket not in _ELAPSED_BUCKETS or stage_failure not in _FIXTURE_FAILURE_CLASSES:
            raise StageFailure("fixture-evidence-invalid")
        names.append(name)
    if names != list(_FIXTURE_STAGE_NAMES[: len(names)]) or (stages[-1]["outcome"] == "passed" and len(stages) != len(_FIXTURE_STAGE_NAMES)):
        raise StageFailure("fixture-evidence-invalid")
    if service_exit == 0:
        if failure_stage or failure_class or any(stage["outcome"] != "passed" for stage in stages):
            raise StageFailure("fixture-evidence-invalid")
    elif stages[-1]["outcome"] != "failed" or failure_stage != stages[-1]["name"] or failure_class != stages[-1]["failure_class"]:
        raise StageFailure("fixture-evidence-invalid")
    return payload


def _run_actual_migration_upgrade(workdir: Path, migration_env: dict[str, str], database_name: str) -> dict[str, object]:
    """Apply the real historical prefix, then upgrade the same disposable DB."""
    from pg_migration_runner import PsqlExecutor, connection_environment

    source_manifest = json.loads((ROOT / "migrations" / "migration_manifest.json").read_text(encoding="utf-8"))
    entries = source_manifest.get("migrations")
    if not isinstance(entries, list):
        raise RuntimeError("migration-upgrade-manifest")
    prefix_entries = [entry for entry in entries if isinstance(entry, dict) and int(entry.get("sequence", 0)) < 32]
    if not prefix_entries or len(prefix_entries) == len(entries):
        raise RuntimeError("migration-upgrade-prefix")
    upgrade_root = workdir / "migration-upgrade-root"
    migrations_dir = upgrade_root / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=False)
    for entry in prefix_entries:
        migration_id = entry.get("id")
        if not isinstance(migration_id, str):
            raise RuntimeError("migration-upgrade-entry")
        shutil.copy2(ROOT / "migrations" / migration_id, migrations_dir / migration_id)
    (migrations_dir / "migration_manifest.json").write_text(
        json.dumps({"version": 1, "migrations": prefix_entries}, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    migration_admin_database_url = migration_env["MIGRATION_TEST_DATABASE_URL"]
    parsed = urlsplit(migration_admin_database_url)
    upgrade_url = urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", parsed.query, parsed.fragment))
    admin_env = connection_environment({**migration_env, "DATABASE_URL": migration_admin_database_url})
    exists = _run(["psql", "-At", "-c", f"SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = '{database_name}')"], env=admin_env, timeout=60)
    if exists.returncode or exists.stdout.strip() != "f":
        raise RuntimeError("migration-upgrade-database-reuse")
    create = _run(["psql", "-v", "ON_ERROR_STOP=1", "-c", f'CREATE DATABASE "{database_name}"'], env=admin_env, timeout=60)
    if create.returncode:
        raise RuntimeError("migration-upgrade-create-database")
    upgrade_env = dict(migration_env)
    upgrade_env["DATABASE_URL"] = upgrade_url
    executor = PsqlExecutor(env=upgrade_env, cwd=ROOT)
    from pg_migration_runner import MigrationRunner

    prefix_runner = MigrationRunner(upgrade_root, executor=executor)
    prefix_runner.apply(backup_acknowledged=True)
    upgraded_runner = MigrationRunner(ROOT, executor=executor)
    pending = [migration.migration_id for migration in upgraded_runner.plan().pending]
    if "029_video_semantic_segments.sql" not in pending:
        raise RuntimeError("migration-upgrade-pending")
    upgraded_runner.apply(backup_acknowledged=True)
    if upgraded_runner.plan().pending:
        raise RuntimeError("migration-upgrade-repeat")
    history = upgraded_runner.status()
    if not history or any(row["state"] != "applied" or not re.fullmatch(r"[0-9a-f]{64}", str(row["checksum"])) for row in history):
        raise RuntimeError("migration-upgrade-history")
    return {"database_fresh": True, "history_entries": len(history), "checksums_verified": True}


def _load_video_stage_evidence(path: Path) -> dict[str, object]:
    """Validate the small, path-free summary emitted by the video pytest stage."""
    if not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError("video stage evidence is missing or oversized")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("video stage evidence schema is invalid")
    video = payload.get("video")
    if not isinstance(video, dict) or not {"probe", "asset", "segment_count", "time_ranges"}.issubset(video) or set(video) - {"probe", "asset", "segment_count", "time_ranges", "recovery"}:
        raise ValueError("video stage evidence fields are invalid")
    probe, asset, ranges = video["probe"], video["asset"], video["time_ranges"]
    recovery = video.get("recovery", {"app_restarted_during_processing": False, "terminal_persisted": False})
    if not isinstance(probe, dict) or not isinstance(asset, dict) or not isinstance(ranges, list) or recovery not in ({"app_restarted_during_processing": False, "terminal_persisted": False}, {"app_restarted_during_processing": True, "terminal_persisted": True}):
        raise ValueError("video stage evidence values are invalid")
    required_probe = {"ffmpeg", "ffprobe", "duration_ms", "fps", "width", "height", "video_codec", "has_audio", "audio_codec"}
    required_asset = {"media_id", "duration_ms", "fps", "has_audio", "profile_version"}
    if set(probe) != required_probe or set(asset) != required_asset:
        raise ValueError("video stage evidence metadata is incomplete")
    if not (probe["ffmpeg"] is True and probe["ffprobe"] is True and isinstance(probe["has_audio"], bool) and isinstance(asset["has_audio"], bool)):
        raise ValueError("video stage tool evidence is invalid")
    for value in (probe["duration_ms"], probe["width"], probe["height"], asset["duration_ms"]):
        if not isinstance(value, int) or value <= 0:
            raise ValueError("video stage numeric evidence is invalid")
    for value in (probe["fps"], asset["fps"]):
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
            raise ValueError("video stage fps evidence is invalid")
    if not isinstance(asset["media_id"], str) or not asset["media_id"] or asset["profile_version"] != "v2":
        raise ValueError("video stage asset evidence is invalid")
    if not isinstance(probe["video_codec"], str) or not probe["video_codec"] or not isinstance(probe["audio_codec"], str):
        raise ValueError("video stage codec evidence is invalid")
    if not isinstance(video["segment_count"], int) or video["segment_count"] <= 1 or len(ranges) != video["segment_count"]:
        raise ValueError("video stage segment evidence is invalid")
    previous_end = -1
    checked_ranges: list[dict[str, int]] = []
    for expected_index, item in enumerate(ranges):
        if not isinstance(item, dict) or set(item) != {"index", "start_ms", "end_ms"}:
            raise ValueError("video stage range evidence is invalid")
        index, start, end = item["index"], item["start_ms"], item["end_ms"]
        if index != expected_index or not all(isinstance(value, int) for value in (start, end)) or not 0 <= start < end <= asset["duration_ms"]:
            raise ValueError("video stage time range is invalid")
        if previous_end >= 0 and start >= previous_end:
            raise ValueError("video stage ranges do not overlap")
        previous_end = end
        checked_ranges.append({"index": index, "start_ms": start, "end_ms": end})
    sanitized = {
        "probe": {key: probe[key] for key in sorted(required_probe)},
        "asset": {key: asset[key] for key in sorted(required_asset)},
        "segment_count": video["segment_count"],
        "time_ranges": checked_ranges,
        "recovery": recovery,
    }
    if _LOCAL_PATH_RE.search(json.dumps(sanitized, ensure_ascii=True)):
        raise ValueError("video stage evidence contains a local path")
    return sanitized


def _load_video_failure_phase(path: Path) -> str:
    allowed = {
        "container-probe", "login", "kb-create", "upload", "task-poll",
        "app-restart", "task-restarted", "task-terminal-failed", "task-timeout",
        "retrieval-health", "storage-probe", "segment-validation", "agent-create", "conversation-create", "conversation-persistence",
        "sse", "media-range", "ungranted-user", "evidence-write",
    }
    try:
        phase = path.read_text(encoding="ascii").strip()
    except OSError:
        return "unknown"
    return phase if phase in allowed else "unknown"


def _http_probe(base: str, path: str) -> None:
    with urllib.request.urlopen(base + path, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"probe-{path}")


def _fixed_runtime_stages(base: str, evidence: list[dict[str, object]]) -> None:
    """Run the deterministic non-provider probes required by Stage 3."""
    for name, path in (("txt-markdown-retrieval", "/api/health"), ("observability", "/metrics")):
        if not _stage(name, lambda path=path: _http_probe(base, path), evidence):
            raise RuntimeError(name)
    def concurrent_probe(level: int) -> None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=level) as pool:
            results = list(pool.map(lambda _: urllib.request.urlopen(base + "/api/live", timeout=15).status, range(level)))
        if any(status != 200 for status in results):
            raise RuntimeError(f"concurrency-{level}")
    for level in (1, 3, 5):
        if not _stage(f"concurrency-{level}", lambda level=level: concurrent_probe(level), evidence):
            raise RuntimeError(f"concurrency-{level}")
    if not _stage("duplicate", lambda: _http_probe(base, "/api/health"), evidence):
        raise RuntimeError("duplicate")


def _load_browser_stage_evidence(path: Path) -> dict[str, object]:
    if not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError("browser stage evidence is missing or oversized")
    payload = json.loads(path.read_text(encoding="utf-8"))
    matrices = payload.get("matrices") if isinstance(payload, dict) else None
    parity = payload.get("api_resource_parity") if isinstance(payload, dict) else None
    navigation = payload.get("thread_navigation_contract") if isinstance(payload, dict) else None
    expected_roles = {"super_admin", "dept_admin", "teacher", "assistant", "student"}
    expected_viewports = {"desktop", "mobile"}
    expected_contexts = {(role, viewport) for role in expected_roles for viewport in expected_viewports}
    if payload.get("schema_version") != 2 or payload.get("browser") != "playwright" or payload.get("complete_browser_evidence") is not True:
        raise ValueError("browser stage evidence schema is invalid")
    required_parity = {
        "same_agent", "same_conversation", "same_kb", "upload_terminal_count",
        "retrieval_ready", "retrieval_context_present", "retrieval_video_anchor_count",
        "done_received", "done_fallback", "citation_count", "video_segment_citation_count",
        "citation_rendered", "video_playback",
    }
    if not isinstance(parity, dict) or set(parity) != required_parity:
        raise ValueError("browser API resource parity evidence is invalid")
    required_true = {
        "same_agent", "same_conversation", "same_kb", "retrieval_ready",
        "retrieval_context_present", "done_received", "citation_rendered", "video_playback",
    }
    if any(parity[key] is not True for key in required_true):
        raise ValueError("browser API resource parity did not preserve the same resource")
    for key in ("upload_terminal_count", "retrieval_video_anchor_count", "citation_count", "video_segment_citation_count"):
        if not isinstance(parity[key], int) or not 0 <= parity[key] <= 999:
            raise ValueError("browser API resource parity count is invalid")
    if parity["upload_terminal_count"] < 1 or parity["retrieval_video_anchor_count"] < 1 or parity["citation_count"] < 1 or parity["video_segment_citation_count"] < 1:
        raise ValueError("browser API resource parity citation coverage is invalid")
    if not isinstance(parity["done_fallback"], bool) or parity["done_fallback"]:
        raise ValueError("browser API resource parity unexpectedly fell back")
    if _LOCAL_PATH_RE.search(json.dumps(parity, ensure_ascii=True)):
        raise ValueError("browser API resource parity contains a local path")
    required_navigation = {
        "thread_query_present", "thread_query_value_present", "thread_list_order_matches_expected",
        "decoy_thread_present", "target_thread_present", "initial_navigation_path_matches_target",
        "selected_thread_matches_target", "detail_response_thread_matches_target",
        "stale_response_ignored", "navigation_path_matches_target", "active_thread_matches_target",
        "persisted_message_thread_matches_target", "conversation_locator_unique_visible",
        "request_response_counts_match_expected",
    }
    if not isinstance(navigation, dict) or any(navigation.get(key) is not True for key in required_navigation):
        raise ValueError("browser thread navigation evidence is invalid")
    if navigation.get("timeout_or_abort") is not False or navigation.get("console_error_count") != 0 or navigation.get("page_error_count") != 0:
        raise ValueError("browser thread navigation client evidence is invalid")
    trace = navigation.get("navigation_trace")
    if not isinstance(trace, list) or not trace or len(trace) > 128 or _LOCAL_PATH_RE.search(json.dumps(navigation, ensure_ascii=True)):
        raise ValueError("browser thread navigation trace is invalid")
    if not isinstance(matrices, dict) or set(matrices) != {"new_video", "nonvideo", "legacy_video"}:
        raise ValueError("browser matrix evidence is invalid")

    def validate_errors(item: dict[str, object]) -> None:
        role_errors = item.get("errors")
        if not isinstance(role_errors, dict) or set(role_errors) != {"console", "page", "expected_detail_request", "non_expected_request", "aborted"} or any(not isinstance(value, int) or value != 0 for value in role_errors.values()):
            raise ValueError("browser role client errors were not controlled")

    def validate_common(item: dict[str, object], path_name: str) -> None:
        if not isinstance(item, dict) or item.get("path") != path_name or item.get("passed") is not True or item.get("failure_class") is not None:
            raise ValueError(f"browser {path_name} result is invalid")
        if item.get("session_restore") is not True or item.get("logout") is not True:
            raise ValueError("browser session evidence is invalid")
        role = item.get("role")
        if item.get("shared_kb_read") is not True:
            raise ValueError("browser shared KB read evidence is invalid")
        expected_manage = "allowed" if role in {"super_admin", "dept_admin"} else "denied"
        if item.get("user_management") != expected_manage:
            raise ValueError("browser user management evidence is invalid")
        expected_write = "denied" if role == "student" else "allowed"
        if item.get("kb_write") != expected_write:
            raise ValueError("browser KB write evidence is invalid")
        required_observations = {
            "query_started", "stream_completed", "stream_citation_state_present",
            "persisted_refresh_preserved", "locator_binding_matches",
            "legacy_contract_ok", "nonvideo_player_absent",
        }
        if any(not isinstance(item.get(key), bool) for key in required_observations | {"player_rendered"}):
            raise ValueError(f"browser {path_name} observations are incomplete")
        for key in ("citation_count", "video_segment_count", "player_count", "range_label_count"):
            if not isinstance(item.get(key), int) or not 0 <= item[key] <= 999:
                raise ValueError(f"browser {path_name} count is invalid")
        if path_name != "legacy_video":
            detail = item.get("page_detail_get")
            if not isinstance(detail, dict) or set(detail) != {"response_count", "status", "ok"} or detail.get("response_count", 0) < 1 or detail.get("status") != 200 or detail.get("ok") is not True:
                raise ValueError("browser page detail request evidence is invalid")
        validate_errors(item)

    validated_matrices: dict[str, list[dict[str, object]]] = {}
    for path_name, entries in matrices.items():
        if not isinstance(entries, list) or len(entries) != 10 or {(item.get("role"), item.get("viewport")) for item in entries if isinstance(item, dict)} != expected_contexts:
            raise ValueError(f"browser {path_name} matrix is incomplete")
        for item in entries:
            validate_common(item, path_name)
            if path_name == "new_video":
                if item.get("query_started") is not True or item.get("stream_completed") is not True or item.get("stream_citation_state_present") is not True or item.get("persisted_refresh_preserved") is not True or item.get("locator_binding_matches") is not True or item.get("player_rendered") is not True or item.get("video_retrieval") is not True or item.get("adjacent_ranges") is not True or item.get("video_playback") is not True or item.get("expected_active_thread_match") is not True:
                    raise ValueError("browser video playback coverage is invalid")
                player = item.get("player")
                if not isinstance(player, dict) or player.get("present") is not True or player.get("visible") is not True or player.get("segment_count") < 2:
                    raise ValueError("browser video player evidence is invalid")
                seek = item.get("seek")
                if not isinstance(seek, dict) or not isinstance(seek.get("actual_seconds"), (int, float)) or not isinstance(seek.get("delta_seconds"), (int, float)) or seek.get("controlled_blob") is not True or seek["delta_seconds"] > 1:
                    raise ValueError("browser seek evidence is invalid")
                media = item.get("authorized_media")
                if not isinstance(media, dict) or set(media) != {"media", "media_range", "content_range"} or media.get("media") != 200 or media.get("media_range") != 206 or not isinstance(media.get("content_range"), str) or not media["content_range"]:
                    raise ValueError("browser authorized media coverage is invalid")
            elif path_name == "nonvideo":
                if item.get("query_started") is not True or item.get("stream_completed") is not True or item.get("stream_citation_state_present") is not True or item.get("persisted_refresh_preserved") is not True or item.get("locator_binding_matches") is not True or item.get("player_rendered") is not False or item.get("nonvideo_player_absent") is not True or item.get("video_retrieval") is not False or item.get("player_count") != 0 or item.get("range_label_count") != 0:
                    raise ValueError("browser non-video presentation leaked video controls")
                fixture_citations = item.get("fixture_citations")
                if not isinstance(fixture_citations, list) or len(fixture_citations) != 3 or any(not isinstance(name, str) or not name for name in fixture_citations) or len(set(fixture_citations)) != 3:
                    raise ValueError("browser non-video fixture citation evidence is invalid")
            elif path_name == "legacy_video":
                if item.get("legacy_contract_ok") is not True or item.get("player_rendered") is not False or item.get("legacy_result") not in {"compatible", "rejected"} or item.get("video_segment_count") != 0:
                    raise ValueError("browser legacy video contract is invalid")
        validated_matrices[path_name] = entries

    for item in validated_matrices["new_video"]:
        logout_denied = item.get("logout_denied")
        if not isinstance(logout_denied, dict) or set(logout_denied) != {"api", "media", "media_range"} or any(logout_denied[key] not in {401, 403} for key in logout_denied):
            raise ValueError("browser logout denial evidence is invalid")
    upload_roles = [item for item in validated_matrices["new_video"] if item.get("upload")]
    if len(upload_roles) != 1 or (upload_roles[0].get("role"), upload_roles[0].get("viewport")) != ("super_admin", "desktop") or upload_roles[0].get("upload_progress") is not True or upload_roles[0].get("upload_terminal") is not True:
        raise ValueError("browser upload evidence is invalid")
    anonymous = payload.get("anonymous")
    if not isinstance(anonymous, dict) or set(anonymous) != {"kb", "media", "media_range"} or any(anonymous[key] not in {401, 403} for key in anonymous):
        raise ValueError("browser anonymous media evidence is invalid")
    counts = payload.get("client_error_counts")
    if not isinstance(counts, dict) or set(counts) != {"console", "page", "expected_detail_request", "non_expected_request", "aborted"} or any(not isinstance(counts[key], int) or counts[key] < 0 for key in counts):
        raise ValueError("browser client errors were not controlled")
    if any(counts[key] != 0 for key in counts):
        raise ValueError("browser client errors were not controlled")
    return {"complete": True, "matrices": validated_matrices, "api_resource_parity": parity, "thread_navigation_contract": navigation, "anonymous": anonymous, "client_error_counts": counts}


def _load_phase_a_browser_evidence(path: Path) -> dict[str, object]:
    if not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError("phase A browser evidence is missing or oversized")
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected_stages = {"navigation", "query_submit", "sse_response", "sse_body", "sse_framing", "sse_json", "sse_done", "persisted_conversation", "persisted_assistant", "persisted_citation", "assistant_dom", "citation_dom", "player_dom", "visibility", "reload", "media", "range"}
    if not isinstance(payload, dict) or payload.get("schema_version") not in {2, 4} or payload.get("browser") != "playwright" or payload.get("phase_a_representative") is not True:
        raise ValueError("phase A browser evidence schema is invalid")
    if _LOCAL_PATH_RE.search(json.dumps(payload, ensure_ascii=True)):
        raise ValueError("phase A browser evidence contains a local path")
    if payload.get("runtime_status") != "passed" or payload.get("failure_class") is not None or payload.get("timeout_stage") != "" or payload.get("representative_path") != "super_admin_desktop_new_video":
        raise ValueError("phase A browser evidence did not pass")
    trace = payload.get("phase_a")
    required_trace_keys = {"status", "failure_class", "timeout_stage", "stages", "client"}
    if not isinstance(trace, dict):
        raise ValueError("phase A browser diagnostic trace is invalid")
    valid_trace_shape = set(trace) == required_trace_keys if payload.get("schema_version") == 2 else required_trace_keys.issubset(trace)
    if not valid_trace_shape or trace.get("status") != "passed" or trace.get("failure_class") is not None or trace.get("timeout_stage") != "" or set(trace.get("stages", {})) != expected_stages:
        raise ValueError("phase A browser diagnostic trace is invalid")
    bucket_names = {"lt_1s", "lt_5s", "lt_30s", "gte_30s"}
    required_stage_keys = {"state", "started_at", "ended_at", "elapsed_bucket", "count", "http_status"}
    for item in trace["stages"].values():
        if not isinstance(item, dict):
            raise ValueError("phase A browser diagnostic stage is invalid")
        valid_stage_shape = set(item) == required_stage_keys if payload.get("schema_version") == 2 else required_stage_keys.issubset(item)
        if not valid_stage_shape or item.get("state") != "passed" or item.get("elapsed_bucket") not in bucket_names or not isinstance(item.get("count"), int) or not isinstance(item.get("http_status"), int):
            raise ValueError("phase A browser diagnostic stage is invalid")
        started_at = item.get("started_at")
        ended_at = item.get("ended_at")
        if not isinstance(started_at, int) or not isinstance(ended_at, int) or started_at <= 0 or ended_at < started_at:
            raise ValueError("phase A browser diagnostic timing is invalid")
        elapsed_ms = ended_at - started_at
        expected_bucket = "lt_1s" if elapsed_ms < 1_000 else "lt_5s" if elapsed_ms < 5_000 else "lt_30s" if elapsed_ms < 30_000 else "gte_30s"
        if item["elapsed_bucket"] != expected_bucket:
            raise ValueError("phase A browser diagnostic elapsed bucket is invalid")
    client = trace.get("client")
    required_client_keys = {"console_error_count", "page_error_count", "dom_mutation_count", "locator_count"}
    if not isinstance(client, dict):
        raise ValueError("phase A browser client evidence is invalid")
    valid_client_shape = set(client) == required_client_keys if payload.get("schema_version") == 2 else required_client_keys.issubset(client)
    if not valid_client_shape or any(not isinstance(client[key], int) or not 0 <= client[key] <= 999 for key in required_client_keys):
        raise ValueError("phase A browser client evidence is invalid")
    matrix = payload.get("matrix")
    if not isinstance(matrix, dict) or matrix.get("role") != "super_admin" or matrix.get("viewport") != "desktop" or matrix.get("path") != "new_video" or matrix.get("passed") is not True:
        raise ValueError("phase A browser representative matrix is invalid")
    return {
        "complete": True,
        "representative": True,
        "trace": {
            **{key: trace[key] for key in required_trace_keys},
            **({key: trace[key] for key in ("current_stage", "setup_navigation") if key in trace} if payload.get("schema_version") == 4 else {}),
        },
        "matrix": matrix,
    }


def _load_browser_failure_class(path: Path) -> str:
    """Return a bounded Browser UAT failure class without retaining diagnostics."""
    if not path.is_file() or path.stat().st_size > 16 * 1024:
        return "unknown"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return "unknown"
    value = payload.get("failure_class") if isinstance(payload, dict) else None
    if value is None and isinstance(payload, dict) and payload.get("browser_citation_only") is True:
        probe = payload.get("citation_probe")
        value = probe.get("failure_class") if isinstance(probe, dict) else None
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9_-]{1,80}", value):
        return "unknown"
    return value


def _load_upload_diagnosis_evidence(path: Path) -> dict[str, object]:
    if not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError("upload diagnosis evidence is missing or oversized")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or payload.get("upload_diagnosis") is not True:
        raise ValueError("upload diagnosis evidence schema is invalid")
    if payload.get("upload_batch_status") != 200 or payload.get("upload_progress") is not True:
        raise ValueError("upload diagnosis did not retain successful batch evidence")
    observations = payload.get("observations")
    required = {"task_http_status", "task_count", "task_status", "task_status_timeline", "task_reason_class", "worker_consumed", "document_http_status", "document_count", "document_status", "retrieval_http_status", "retrieval_ready", "video_segments_http_status", "video_segment_count"}
    if not isinstance(observations, dict) or not required.issubset(observations):
        raise ValueError("upload diagnosis observations are incomplete")
    if not isinstance(observations["task_status_timeline"], list) or len(observations["task_status_timeline"]) > 90:
        raise ValueError("upload diagnosis timeline is invalid")
    if _LOCAL_PATH_RE.search(json.dumps(payload, ensure_ascii=True)):
        raise ValueError("upload diagnosis evidence contains a local path")
    return {"complete": True, "upload_diagnosis": True, "upload_batch_status": 200, "upload_progress": True, "upload_terminal": payload.get("upload_terminal") is True, "observations": observations}


def _write_citation_probe_failure_evidence(path: Path, *, run_id: str, owner: str, project: str, failure_class: str) -> None:
    """Persist only a bounded harness-startup failure matrix when Browser writes nothing."""
    if failure_class not in {"browser-evidence-missing", "citation_probe_automation", "citation_probe_timeout"}:
        failure_class = "browser-evidence-missing"
    phases: list[dict[str, object]] = []
    for phase in sorted(_CITATION_PROBE_PHASES):
        item: dict[str, object] = {"phase": phase, "elapsed_bucket": "lt_30s"}
        if phase in {"timeout_stage", "failure_class"}:
            item["observed"] = True
        elif phase in {"body_byte_count", "done_citation_count", "sse_done_citation_count", "response_body_byte_count", "sse_line_count", "sse_data_line_count", "sse_json_parse_error_count"}:
            item["count"] = 0
        elif phase in {"response_status", "authorized_media_status", "range_status"}:
            item["http_status"] = 0
        else:
            item["observed"] = False
        phases.append(item)
    payload = {
        "schema_version": 3,
        "browser": "playwright",
        "browser_citation_only": True,
        "run_id": run_id,
        "owner": owner,
        "compose_project": project,
        "runtime_status": "run_failed",
        "browser_profile": {"created": False, "used": False, "context_closed": False, "cleaned": False},
        "browser_fixture": {"owned_by_run": True, "created": True},
        "old_run_evidence_used_as_result": False,
        "probe_process_created_docker_resources": 0,
        "citation_probe": {
            **{phase: False for phase in _CITATION_PROBE_PHASES if phase not in {"response_status", "body_read_error_class", "body_byte_count", "done_citation_count", "response_body_byte_count", "sse_line_count", "sse_data_line_count", "sse_json_parse_error_count", "sse_done_citation_count", "authorized_media_status", "range_status", "timeout_stage", "failure_class"}},
            "response_status": 0,
            "response_content_type": "",
            "body_read_error_class": "unavailable",
            "body_byte_count": 0,
            "done_citation_count": 0,
            "response_body_byte_count": 0,
            "sse_line_count": 0,
            "sse_data_line_count": 0,
            "sse_json_parse_error_count": 0,
            "sse_done_citation_count": 0,
            "sse_done_citations_shape": "absent",
            "sse_done_citations_count": None,
            "persisted_assistant_citations_shape": "absent",
            "persisted_assistant_citations_count": None,
            "retrieval_context_shape": "unknown",
            "retrieval_video_anchor_detection": "unavailable",
            "citation_video_segment_shape": "absent",
            "citation_video_segment_count": 0,
            "citation_media_id_present": False,
            "citation_document_id_present": False,
            "query_thread_matches_target": False,
            "query_id_thread_id_match": False,
            "request_failure": {"stage": "failure_class", "path": "", "reason_class": failure_class},
            "authorized_media_status": 0,
            "range_status": 0,
            "timeout_stage": "failure_class",
            "failure_class": failure_class,
            "phases": phases,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8")


def _validate_citation_probe_observations(probe: dict[str, object]) -> None:
    """Validate only shape/count diagnostics; never accept raw citation payloads."""
    shape_fields = ("sse_done_citations_shape", "persisted_assistant_citations_shape")
    for field in shape_fields:
        if probe.get(field) not in _CITATION_ARRAY_SHAPES:
            raise ValueError("citation observation shape is invalid")
    for field, shape_field in (
        ("sse_done_citations_count", "sse_done_citations_shape"),
        ("persisted_assistant_citations_count", "persisted_assistant_citations_shape"),
    ):
        value = probe.get(field)
        if probe[shape_field] == "array":
            if not isinstance(value, int) or not 0 <= value <= 999:
                raise ValueError("citation observation count is invalid")
        elif value is not None:
            raise ValueError("citation observation count must be null when non-array")
    if probe.get("retrieval_context_shape") not in _RETRIEVAL_CONTEXT_SHAPES:
        raise ValueError("retrieval context shape is invalid")
    if probe.get("retrieval_video_anchor_detection") not in _RETRIEVAL_ANCHOR_DETECTIONS:
        raise ValueError("retrieval anchor detection is invalid")
    if (probe.get("retrieval_context_shape") == "string") != (probe.get("retrieval_video_anchor_detection") in {"matched", "not_matched"}):
        raise ValueError("retrieval anchor detection requires string context")
    if probe.get("citation_video_segment_shape") not in _CITATION_VIDEO_SEGMENT_SHAPES:
        raise ValueError("citation video segment shape is invalid")
    if not isinstance(probe.get("citation_video_segment_count"), int) or not 0 <= probe["citation_video_segment_count"] <= 999:
        raise ValueError("citation video segment count is invalid")
    for field in ("citation_media_id_present", "citation_document_id_present"):
        if not isinstance(probe.get(field), bool):
            raise ValueError("citation identifier observation is invalid")
    if not isinstance(probe.get("query_thread_matches_target"), bool):
        raise ValueError("query/thread match observation is invalid")
    if not isinstance(probe.get("query_id_thread_id_match"), bool):
        raise ValueError("query id/thread id match observation is invalid")
    failure = probe.get("request_failure")
    if not isinstance(failure, dict) or set(failure) != {"stage", "path", "reason_class"} or any(not isinstance(failure[key], str) for key in failure):
        raise ValueError("request failure observation is invalid")
    if failure["path"] and not _SAFE_FAILURE_PATH.fullmatch(failure["path"]):
        raise ValueError("request failure path is unsafe")
    if failure["stage"] or failure["path"] or failure["reason_class"]:
        if not failure["stage"] or not failure["reason_class"]:
            raise ValueError("request failure observation is incomplete")
        if not re.fullmatch(r"[a-z0-9_-]{1,80}", failure["stage"], re.IGNORECASE) or not re.fullmatch(r"[a-z0-9_-]{1,80}", failure["reason_class"], re.IGNORECASE):
            raise ValueError("request failure reason is unsafe")


def _require_probe_image(image: str, runtime_revision: str, env: dict[str, str]) -> dict[str, str]:
    """Bind a pre-build navigation probe to one locally inspected runtime image."""
    if not re.fullmatch(r"[0-9a-f]{40}", runtime_revision):
        raise ValueError("navigation probe runtime revision is invalid")
    inspected = _run(["docker", "image", "inspect", image], env=env, timeout=30)
    if inspected.returncode:
        raise ValueError("navigation probe image is unavailable")
    try:
        data = json.loads(inspected.stdout)[0]
        labels = data["Config"]["Labels"]
        revision = labels.get("org.opencontainers.image.revision")
        platform = f"{data['Os']}/{data['Architecture']}"
        image_id = str(data["Id"])
        repo_digests = [str(value) for value in data.get("RepoDigests") or []]
    except (IndexError, KeyError, TypeError, ValueError):
        raise ValueError("navigation probe image identity is invalid") from None
    if revision != runtime_revision or platform != "linux/amd64" or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise ValueError("navigation probe image revision or platform is invalid")
    digest = next((item.rsplit("@", 1)[-1] for item in repo_digests if re.fullmatch(r".+@sha256:[0-9a-f]{64}", item)), image_id)
    return {"tag": image, "revision": runtime_revision, "platform": platform, "digest": digest, "image_id": image_id}


def _load_navigation_probe_evidence(path: Path, *, run_id: str, owner: str, project: str) -> dict[str, object]:
    if not path.is_file() or path.stat().st_size > 32 * 1024:
        raise ValueError("navigation probe evidence is missing or oversized")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        raise ValueError("navigation probe evidence is invalid") from None
    if not isinstance(payload, dict) or payload.get("schema_version") != 2 or payload.get("browser") != "playwright" or payload.get("browser_navigation_only") is not True:
        raise ValueError("navigation probe evidence schema is invalid")
    if payload.get("run_id") != run_id or payload.get("owner") != owner or payload.get("compose_project") != project or payload.get("runtime_status") != "passed":
        raise ValueError("navigation probe evidence identity is invalid")
    profile = payload.get("browser_profile")
    fixture = payload.get("browser_fixture")
    navigation = payload.get("navigation_probe")
    if profile != {"created": True, "used": True, "context_closed": True, "cleaned": True} or fixture != {"owned_by_run": True, "created": True}:
        raise ValueError("navigation probe lifecycle evidence is invalid")
    if not isinstance(navigation, dict) or navigation.get("timeout_or_abort") is not False:
        raise ValueError("navigation probe navigation evidence is invalid")
    required = {
        "page_ready", "conversation_locator_unique_visible", "decoy_thread_present", "target_thread_present",
        "selected_thread_matches_target", "active_thread_match", "stale_response_ignored",
        "navigation_path_matches_target", "active_thread_matches_target", "persisted_message_thread_matches_target",
        "request_response_counts_match_expected",
    }
    if any(navigation.get(key) is not True for key in required):
        raise ValueError("navigation probe assertions are incomplete")
    for key in ("sidebar_locator_count", "main_conversation_locator_count", "target_thread_locator_count", "decoy_locator_count"):
        if not isinstance(navigation.get(key), int) or not 1 <= navigation[key] <= 999:
            raise ValueError("navigation probe locator count is invalid")
    trace = navigation.get("navigation_trace")
    if not isinstance(trace, dict) or trace.get("failure_class") is not None or trace.get("timeout_stage") != "":
        raise ValueError("navigation probe trace is invalid")
    phases = trace.get("phases")
    if not isinstance(phases, list) or not phases or len(phases) > 128:
        raise ValueError("navigation probe phase evidence is invalid")
    phase_names = {entry.get("phase") for entry in phases if isinstance(entry, dict)}
    if not _NAVIGATION_PROBE_PHASES <= phase_names:
        raise ValueError("navigation probe required phases are missing")
    for entry in phases:
        if not isinstance(entry, dict) or not isinstance(entry.get("phase"), str) or entry.get("status") not in {"started", "completed", "observed"} or entry.get("elapsed_bucket") not in {"lt_1s", "lt_5s", "lt_30s", "gte_30s"}:
            raise ValueError("navigation probe phase evidence is invalid")
    if _LOCAL_PATH_RE.search(json.dumps(payload, ensure_ascii=True)):
        raise ValueError("navigation probe evidence contains a local path")
    return {"complete": True, "navigation": navigation, "browser_profile": profile, "browser_fixture": fixture}


def _load_citation_probe_evidence(path: Path, *, run_id: str, owner: str, project: str) -> dict[str, object]:
    if not path.is_file() or path.stat().st_size > 32 * 1024:
        raise ValueError("citation probe evidence is missing or oversized")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        raise ValueError("citation probe evidence is invalid") from None
    if not isinstance(payload, dict) or payload.get("schema_version") != 3 or payload.get("browser") != "playwright" or payload.get("browser_citation_only") is not True:
        raise ValueError("citation probe evidence schema is invalid")
    diagnosis_only = payload.get("browser_citation_diagnosis_only") is True
    expected_status = "passed" if not diagnosis_only else payload.get("runtime_status")
    if payload.get("run_id") != run_id or payload.get("owner") != owner or payload.get("compose_project") != project or (not diagnosis_only and payload.get("runtime_status") != expected_status):
        raise ValueError("citation probe evidence identity is invalid")
    if payload.get("old_run_evidence_used_as_result") is not False or payload.get("probe_process_created_docker_resources") != 0:
        raise ValueError("citation probe evidence provenance is invalid")
    if payload.get("browser_profile") != {"created": True, "used": True, "context_closed": True, "cleaned": True}:
        raise ValueError("citation probe profile lifecycle is invalid")
    if payload.get("browser_fixture") != {"owned_by_run": True, "created": True}:
        raise ValueError("citation probe fixture lifecycle is invalid")
    probe = payload.get("citation_probe")
    if not isinstance(probe, dict) or (not diagnosis_only and (probe.get("failure_class") is not None or probe.get("timeout_stage") != "")):
        raise ValueError("citation probe evidence status is invalid")
    _validate_citation_probe_observations(probe)
    if diagnosis_only:
        return {"complete": payload.get("runtime_status") == "passed", "citation_probe": probe, "browser_profile": payload["browser_profile"], "browser_fixture": payload["browser_fixture"]}
    required_true = {
        "query_submit_started", "query_submit_completed", "target_query_identity_observed",
        "stream_response_started", "stream_response_completed", "sse_done_received",
        "sse_done_thread_matches_target", "streaming_assistant_found", "streaming_citation_found",
        "streaming_video_player_found", "player_visible", "persisted_conversation_get",
        "persisted_assistant_found", "persisted_video_segments_found", "reload_started",
        "reload_completed", "reloaded_player_visible",
    }
    if any(probe.get(key) is not True for key in required_true):
        raise ValueError("citation probe assertions are incomplete")
    if not isinstance(probe.get("sse_done_citation_count"), int) or not 1 <= probe["sse_done_citation_count"] <= 999:
        raise ValueError("citation probe citation count is invalid")
    for key in ("response_wait_started", "response_received", "body_read_started", "body_read_completed", "request_finished", "done_received", "done_thread_matches_target", "response_body_read_started", "response_body_read_completed", "sse_event_framing"):
        if probe.get(key) is not True:
            raise ValueError("citation probe SSE stage is incomplete")
    if probe.get("response_status") != 200 or probe.get("response_content_type") != "text/event-stream":
        raise ValueError("citation probe response contract is invalid")
    if probe.get("body_read_error_class") != "" or probe.get("request_failed") is not False:
        raise ValueError("citation probe body-read lifecycle is invalid")
    for key in ("body_byte_count", "done_citation_count", "response_body_byte_count", "sse_line_count", "sse_data_line_count"):
        if not isinstance(probe.get(key), int) or not 1 <= probe[key] <= 999:
            raise ValueError("citation probe SSE count is invalid")
    if probe.get("sse_json_parse_error_count") != 0:
        raise ValueError("citation probe SSE JSON parse evidence is invalid")
    for key, expected in (("authorized_media_status", 200), ("range_status", 206)):
        if probe.get(key) != expected:
            raise ValueError("citation probe media status is invalid")
    phases = probe.get("phases")
    if not isinstance(phases, list) or not phases or len(phases) > 64:
        raise ValueError("citation probe phase evidence is invalid")
    phase_names = [item.get("phase") for item in phases if isinstance(item, dict)]
    if len(set(phase_names)) != len(phase_names) or not _CITATION_PROBE_PHASES <= set(phase_names):
        raise ValueError("citation probe phase evidence is incomplete or duplicated")
    for item in phases:
        if not isinstance(item, dict) or item.get("phase") not in _CITATION_PROBE_PHASES or item.get("elapsed_bucket") not in {"lt_1s", "lt_5s", "lt_30s", "gte_30s"}:
            raise ValueError("citation probe phase item is invalid")
        for key in item:
            if key not in {"phase", "elapsed_bucket", "observed", "count", "http_status"}:
                raise ValueError("citation probe phase contains an unsafe field")
    if _LOCAL_PATH_RE.search(json.dumps(payload, ensure_ascii=True)):
        raise ValueError("citation probe evidence contains a local path")
    return {"complete": True, "citation_probe": probe, "browser_profile": payload["browser_profile"], "browser_fixture": payload["browser_fixture"]}


def run_navigation_probe(target_id: str, workdir: Path, commit: str, *, timeout: int = 180) -> dict[str, object]:
    """Run the bounded Browser navigation contract before a full Browser matrix."""
    _require_isolated_venv()
    target = _safe_target(target_id)
    revision = _require_clean_detached_commit(commit)
    identity = _verification_identity(revision, os.environ.copy())
    runtime_revision = os.getenv("ACCEPTANCE_PROBE_RUNTIME_REVISION", "")
    if _run(["git", "merge-base", "--is-ancestor", runtime_revision, revision], env=os.environ.copy(), timeout=20).returncode:
        raise ValueError("navigation probe runtime revision is not an ancestor")
    runtime_paths = set(_run(["git", "diff", "--name-only", f"{runtime_revision}..{revision}"], env=os.environ.copy(), timeout=20).stdout.splitlines())
    if not runtime_paths <= {"scripts/run_isolated_acceptance.py", "tests/acceptance/video_browser_uat.mjs", "tests/test_video_acceptance_contract.py"}:
        raise ValueError("navigation probe runtime diff scope is invalid")
    workdir = workdir.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if temp_root not in workdir.parents or workdir.exists():
        raise ValueError("navigation probe working directory must be a new system-temp child")
    workdir.mkdir(parents=True)
    env = os.environ.copy()
    compose: list[str] | None = None
    manifest: dict[str, object] | None = None
    foreign_before: dict[str, dict[str, object]] | None = None
    stages: list[dict[str, object]] = []
    result: dict[str, object] = {"schema_version": 1, "target_id": target, "revision": revision, "identity": identity, "owner": _ACCEPTANCE_OWNER, "provider_mode": "mock", "non_production": True, "stages": stages}
    try:
        _require_local_docker(env)
        for key in ("DATABASE_URL", "POSTGRES_PASSWORD", "DEFAULT_ADMIN_PASSWORD", "JWT_SECRET", "JWT_REFRESH_SECRET"):
            env.pop(key, None)
        app = _require_probe_image(os.getenv("ACCEPTANCE_APP_IMAGE", ""), runtime_revision, env)
        frontend = _require_probe_image(os.getenv("ACCEPTANCE_FRONTEND_IMAGE", ""), runtime_revision, env)
        browser = _require_probe_image(os.getenv("ACCEPTANCE_BROWSER_IMAGE", ""), runtime_revision, env)
        token = secrets.token_hex(8)
        run_id = f"video54-nav-{time.strftime('%Y%m%d')}-{revision[:7]}-{token}"
        project = f"video54nav_{token}"
        port = str(18080 + secrets.randbelow(1000))
        pg_port = str(19080 + secrets.randbelow(1000))
        password = _secret()
        env.update({
            "ACCEPTANCE_RUN_ID": run_id, "ACCEPTANCE_OWNER": _ACCEPTANCE_OWNER, "ACCEPTANCE_RUN_DIR": str(workdir),
            "ACCEPTANCE_HTTP_PORT": port, "ACCEPTANCE_PG_PORT": pg_port,
            "ACCEPTANCE_APP_IMAGE": app["tag"], "ACCEPTANCE_FRONTEND_IMAGE": frontend["tag"], "ACCEPTANCE_BROWSER_IMAGE": browser["tag"],
            "ACCEPTANCE_POSTGRES_IMAGE": os.getenv("ACCEPTANCE_POSTGRES_IMAGE", "pgvector/pgvector:pg16"), "ACCEPTANCE_REDIS_IMAGE": os.getenv("ACCEPTANCE_REDIS_IMAGE", "redis:7-alpine"),
            "POSTGRES_USER": "acceptance", "POSTGRES_PASSWORD": password, "POSTGRES_DATABASE": f"acceptance_{token}",
            "DATABASE_URL": f"postgresql://acceptance:{password}@postgres:5432/acceptance_{token}",
            "JWT_SECRET": _secret(), "JWT_REFRESH_SECRET": _secret(), "DEFAULT_ADMIN_USERNAME": "acceptance_admin", "DEFAULT_ADMIN_PASSWORD": _secret(),
        })
        result.update({"run_id": run_id, "project": project, "probe_runtime_revision": runtime_revision, "runtime_images": {"app": app, "frontend": frontend, "browser": browser}})
        foreign_before = _docker_inventory(env)
        result["foreign_docker"] = {"before": foreign_before, "after": None, "unchanged": False}
        for source, target_path in (("pgvector-init.sql", "pgvector-init.sql"), ("nginx.conf", "nginx.conf"), ("mock_video_provider.py", "mock_provider.py"), ("video_browser_uat.mjs", "video_browser_uat.mjs")):
            shutil.copy2(ROOT / "tests" / "acceptance" / source, workdir / target_path)
        (workdir / "compose.env").write_text("\n".join(f"{key}={value}" for key, value in env.items() if key.startswith("ACCEPTANCE_") or key in {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DATABASE", "DATABASE_URL", "JWT_SECRET", "JWT_REFRESH_SECRET", "DEFAULT_ADMIN_USERNAME", "DEFAULT_ADMIN_PASSWORD"}), encoding="utf-8")
        manifest = {"schema_version": 2, "run_id": run_id, "owner": _ACCEPTANCE_OWNER, "project": project, "compose_project": project, "revision": revision, "probe_runtime_revision": runtime_revision, "provider_mode": "mock", "runtime_images": result["runtime_images"], "resources": {"containers": [], "volumes": [], "networks": []}, "artifacts": {"browser_profile": "browser-profile"}, "browser_profile": {"path": "browser-profile"}, "browser_profile_final": {"created": False, "used": False, "context_closed": False, "cleaned": False}}
        (workdir / "owner-manifest-initial.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        (workdir / "browser-accounts.json").write_text(json.dumps({"admin": {"username": env["DEFAULT_ADMIN_USERNAME"], "password": env["DEFAULT_ADMIN_PASSWORD"]}}), encoding="utf-8")
        compose = ["docker", "compose", "-p", project, "--env-file", str(workdir / "compose.env"), "-f", str(COMPOSE)]
        if not _stage("compose-up", lambda: _compose_up_probe(compose, env, timeout), stages):
            return result
        manifest["resources"] = _owned_resources(project, run_id, env)
        _record_resource_lifecycle(manifest, env)
        (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        base = f"http://127.0.0.1:{port}"
        if not _stage("health", lambda: _wait_for_health(base), stages):
            return result
        browser_env = dict(env)
        browser_env.update({"VIDEO_BROWSER_NAVIGATION_ONLY": "1", "VIDEO_BROWSER_NAVIGATION_RUN_OWNED": "true", "VIDEO_BROWSER_NAVIGATION_RUN_ID": run_id, "VIDEO_BROWSER_NAVIGATION_OWNER": _ACCEPTANCE_OWNER, "VIDEO_BROWSER_NAVIGATION_COMPOSE_PROJECT": project, "VIDEO_BROWSER_NAVIGATION_RUN_ROOT": "/acceptance/run", "VIDEO_BROWSER_NAVIGATION_PROFILE_DIR": "/acceptance/run/browser-profile", "VIDEO_BROWSER_NAVIGATION_MANIFEST_PATH": "/acceptance/run/manifest.json"})
        probe_path = workdir / "browser-stage-evidence.json"
        def browser_probe() -> None:
            navigation_env_args = [item for key, value in browser_env.items() if key.startswith("VIDEO_BROWSER_NAVIGATION_") for item in ("-e", f"{key}={value}")]
            invoked = _run(compose + ["run", "--rm", "--no-deps", *navigation_env_args, "browser"], env=browser_env, timeout=timeout)
            if invoked.returncode:
                raise StageFailure(_load_browser_failure_class(probe_path))
            result["navigation_probe"] = _load_navigation_probe_evidence(probe_path, run_id=run_id, owner=_ACCEPTANCE_OWNER, project=project)
        if not _stage("navigation-only-probe", browser_probe, stages):
            return result
        profile = manifest["browser_profile_final"]
        assert isinstance(profile, dict)
        profile.update({"created": True, "used": True, "context_closed": True})
        result["release_recommendation"] = "navigation-probe-pass"
        return result
    finally:
        if manifest is not None:
            cleanup_failed = False
            try:
                if not any(manifest["resources"].values()):
                    manifest["resources"] = _owned_resources(str(manifest["project"]), str(manifest["run_id"]), env)
                _reconcile_resource_lifecycle(manifest, env)
                _cleanup_owned(manifest, env)
            except Exception:
                cleanup_failed = True
            try:
                _cleanup_owned_browser_profile(manifest, workdir)
            except Exception:
                cleanup_failed = True
            profile = manifest.get("browser_profile_final")
            if isinstance(profile, dict):
                profile["cleaned"] = not (workdir / "browser-profile").exists()
            stages.append({"name": "cleanup", "outcome": "failed" if cleanup_failed else "passed", "duration_seconds": 0, "detail": "ownership-cleanup" if cleanup_failed else ""})
        if foreign_before is not None:
            foreign_after = _docker_inventory(env)
            unchanged = foreign_after == foreign_before
            result["foreign_docker"] = {"before": foreign_before, "after": foreign_after, "unchanged": unchanged}
            stages.append({"name": "foreign-docker-inventory", "outcome": "passed" if unchanged else "failed", "duration_seconds": 0, "detail": "" if unchanged else "inventory-drift"})
        result["release_recommendation"] = "navigation-probe-pass" if result.get("navigation_probe") and all(stage["outcome"] == "passed" for stage in stages) else "not-releasable"
        if manifest is not None:
            (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
            (workdir / "owner-manifest-final.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
            (workdir / "evidence.json").write_text(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")


def run_citation_probe(target_id: str, workdir: Path, commit: str, *, timeout: int = 900) -> dict[str, object]:
    """Run only the same-run video fixture/Worker setup and citation Browser probe."""
    _require_isolated_venv()
    target = _safe_target(target_id)
    revision = _require_clean_detached_commit(commit)
    identity = _verification_identity(revision, os.environ.copy())
    workdir = workdir.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if temp_root not in workdir.parents or workdir.exists():
        raise ValueError("citation probe working directory must be a new system-temp child")
    workdir.mkdir(parents=True)
    env: dict[str, str] = {}
    compose: list[str] | None = None
    manifest: dict[str, object] | None = None
    fixture: Path | None = None
    foreign_before: dict[str, dict[str, object]] | None = None
    stages: list[dict[str, object]] = []
    result: dict[str, object] = {"schema_version": 3, "target_id": target, "revision": revision, "identity": identity, "owner": _ACCEPTANCE_OWNER, "provider_mode": "mock", "non_production": True, "stages": stages}
    browser_evidence = workdir / "browser-stage-evidence.json"
    fixture_evidence = workdir / "fixture-stage-evidence.json"
    video_stage_evidence = workdir / "video-stage-evidence.json"
    video_phase = workdir / "video-stage-phase.txt"
    legacy_resource = workdir / "legacy-browser-resource.json"
    try:
        env = os.environ.copy()
        _require_local_docker(env)
        runtime_revision = os.getenv("ACCEPTANCE_PROBE_RUNTIME_REVISION", "")
        if runtime_revision != _BEHAVIOR_SHA:
            raise ValueError("citation probe runtime revision must equal the approved behavior SHA")
        for key in ("DATABASE_URL", "POSTGRES_PASSWORD", "DEFAULT_ADMIN_PASSWORD", "JWT_SECRET", "JWT_REFRESH_SECRET"):
            env.pop(key, None)
        resource_token = secrets.token_hex(8)
        run_id = f"video54-citation-{time.strftime('%Y%m%d')}-{revision[:7]}-{resource_token}"
        project = f"video54citation_{resource_token}"
        port = str(18080 + secrets.randbelow(1000))
        pg_port = str(19080 + secrets.randbelow(1000))
        password = _secret()
        env.update({
            "ACCEPTANCE_RUN_ID": run_id, "ACCEPTANCE_OWNER": _ACCEPTANCE_OWNER, "ACCEPTANCE_RUN_DIR": str(workdir),
            "ACCEPTANCE_HTTP_PORT": port, "ACCEPTANCE_PG_PORT": pg_port,
            "ACCEPTANCE_APP_IMAGE": os.getenv("ACCEPTANCE_APP_IMAGE", ""),
            "ACCEPTANCE_FRONTEND_IMAGE": os.getenv("ACCEPTANCE_FRONTEND_IMAGE", ""),
            "ACCEPTANCE_BROWSER_IMAGE": os.getenv("ACCEPTANCE_BROWSER_IMAGE", ""),
            "ACCEPTANCE_POSTGRES_IMAGE": os.getenv("ACCEPTANCE_POSTGRES_IMAGE", "pgvector/pgvector:pg16"), "ACCEPTANCE_REDIS_IMAGE": os.getenv("ACCEPTANCE_REDIS_IMAGE", "redis:7-alpine"),
            "ACCEPTANCE_NGINX_IMAGE": os.getenv("ACCEPTANCE_NGINX_IMAGE", "nginx:alpine"),
            "POSTGRES_USER": "acceptance", "POSTGRES_PASSWORD": password, "POSTGRES_DATABASE": f"acceptance_{resource_token}",
            "DATABASE_URL": f"postgresql://acceptance:{password}@postgres:5432/acceptance_{resource_token}", "JWT_SECRET": _secret(), "JWT_REFRESH_SECRET": _secret(),
            "DEFAULT_ADMIN_USERNAME": "acceptance_admin", "DEFAULT_ADMIN_PASSWORD": _secret(),
        })
        required = ("ACCEPTANCE_APP_IMAGE", "ACCEPTANCE_FRONTEND_IMAGE", "ACCEPTANCE_BROWSER_IMAGE")
        if any(not env[key] for key in required):
            raise ValueError("citation probe image identity inputs are required")
        runtime_images = {
            "app": _require_probe_image(env["ACCEPTANCE_APP_IMAGE"], runtime_revision, env),
            "frontend": _require_probe_image(env["ACCEPTANCE_FRONTEND_IMAGE"], runtime_revision, env),
            "browser": _require_probe_image(env["ACCEPTANCE_BROWSER_IMAGE"], runtime_revision, env),
        }
        result.update({"run_id": run_id, "project": project, "probe_runtime_revision": runtime_revision, "runtime_images": runtime_images})
        foreign_before = _docker_inventory(env)
        result["foreign_docker"] = {"before": foreign_before, "after": None, "unchanged": False}
        for source, target_path in (("pgvector-init.sql", "pgvector-init.sql"), ("nginx.conf", "nginx.conf"), ("mock_video_provider.py", "mock_provider.py"), ("video_browser_uat.mjs", "video_browser_uat.mjs"), ("generate_compat_fixtures.py", "generate_compat_fixtures.py"), ("generate_video_fixture.py", "generate_video_fixture.py")):
            shutil.copy2(ROOT / "tests" / "acceptance" / source, workdir / target_path)
        compose = ["docker", "compose", "-p", project, "--env-file", str(workdir / "compose.env"), "-f", str(COMPOSE)]
        (workdir / "compose.env").write_text("\n".join(f"{key}={value}" for key, value in env.items() if key.startswith("ACCEPTANCE_") or key in {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DATABASE", "DATABASE_URL", "JWT_SECRET", "JWT_REFRESH_SECRET", "DEFAULT_ADMIN_USERNAME", "DEFAULT_ADMIN_PASSWORD"}), encoding="utf-8")
        manifest = {"schema_version": 3, "run_id": run_id, "owner": _ACCEPTANCE_OWNER, "project": project, "compose_project": project, "revision": revision, "probe_runtime_revision": runtime_revision, "identity": identity, "provider_mode": "mock", "runtime_images": runtime_images, "resources": {"containers": [], "volumes": [], "networks": []}, "resource_lifecycle": {kind: {"created": [], "removed": [], "remaining": [], "status_confirmed": False} for kind in ("containers", "volumes", "networks")}, "artifacts": {"browser_profile": "browser-profile"}, "browser_profile": {"path": "browser-profile"}, "browser_profile_final": {"path": "browser-profile", "created": False, "used": False, "context_closed": False, "cleaned": False}}
        (workdir / "owner-manifest-initial.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        (workdir / "browser-accounts.json").write_text(json.dumps({"admin": {"username": env["DEFAULT_ADMIN_USERNAME"], "password": env["DEFAULT_ADMIN_PASSWORD"]}}), encoding="utf-8")
        if not _stage("compose-up", lambda: _compose_up_probe(compose, env, timeout), stages): return result
        manifest["resources"] = _owned_resources(project, run_id, env)
        _record_resource_lifecycle(manifest, env)
        (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        base = f"http://127.0.0.1:{port}"
        if not _stage("health", lambda: _wait_for_health(base), stages): return result
        fixture = workdir / "video-fixture.mp4"
        def fixture_stage() -> None:
            invoked = _run(compose + ["run", "--no-deps", "fixture"], env=env, timeout=timeout)
            fixture_result = _load_fixture_stage_evidence(fixture_evidence, run_id=run_id, owner=_ACCEPTANCE_OWNER, service_exit_code=invoked.returncode)
            result["fixture"] = fixture_result
            manifest["resources"] = _owned_resources(project, run_id, env)
            _reconcile_resource_lifecycle(manifest, env)
            (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
            if invoked.returncode != fixture_result["fixture_service_exit_code"]:
                raise StageFailure("fixture-exit-mismatch")
            if invoked.returncode or not fixture.is_file() or fixture.stat().st_size <= 0:
                raise StageFailure(str(fixture_result["failure_class"] or "video-fixture"))
        if not _stage("video-fixture", fixture_stage, stages): return result
        application_env, _migration_env = _database_test_environments(env, password=password, pg_port=pg_port)
        application_env.update({"VIDEO_ACCEPTANCE_BASE_URL": base, "VIDEO_ACCEPTANCE_FIXTURE": str(fixture), "VIDEO_ACCEPTANCE_DATABASE_URL": application_env["DATABASE_URL"], "VIDEO_ACCEPTANCE_COMPOSE": json.dumps(compose), "VIDEO_ACCEPTANCE_EVIDENCE_PATH": str(video_stage_evidence), "VIDEO_ACCEPTANCE_PHASE_PATH": str(video_phase), "VIDEO_ACCEPTANCE_RESTART_DURING_PROCESSING": "0", "VIDEO_ACCEPTANCE_LEGACY_RESOURCE_PATH": str(legacy_resource)})
        diagnosis_only = os.getenv("VIDEO_CITATION_DIAGNOSIS_ONLY") == "1"
        def worker_stage() -> None:
            if diagnosis_only:
                prepare_env = dict(application_env)
                prepare_env.update({
                    "VIDEO_PROBE_BASE_URL": base,
                    "VIDEO_PROBE_FIXTURE": str(fixture),
                    "VIDEO_PROBE_DATABASE_URL": application_env["DATABASE_URL"],
                    "VIDEO_PROBE_RESOURCE_PATH": str(workdir / "video-probe-resource.json"),
                    "VIDEO_PROBE_ADMIN_PASSWORD": env["DEFAULT_ADMIN_PASSWORD"],
                })
                invoked = _run([sys.executable, "tests/acceptance/prepare_video_citation_probe.py"], env=prepare_env, timeout=timeout)
                _write_redacted_command_output(workdir / "runner-output.json", invoked, label="video-diagnosis-prepare")
                if invoked.returncode: raise StageFailure("video-diagnosis-prepare")
                if not (workdir / "video-probe-resource.json").is_file(): raise StageFailure("video-diagnosis-resource-missing")
                return
            invoked = _run([sys.executable, "-m", "pytest", "-q", "tests/acceptance/test_video_worker_sse.py"], env=application_env, timeout=timeout)
            _write_redacted_command_output(workdir / "runner-output.json", invoked, label="video-worker-sse-recovery")
            if invoked.returncode: raise StageFailure(_classify_pytest_failure(invoked))
            if not video_stage_evidence.is_file(): raise StageFailure("video-evidence-missing")
        if not _stage("video-diagnosis-prepare" if diagnosis_only else "video-worker-sse-recovery", worker_stage, stages): return result
        manifest["browser_fixture"] = {"owned_by_run": True, "created": True}
        (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        browser_env = dict(env)
        browser_env.update({"VIDEO_BROWSER_CITATION_ONLY": "1", "VIDEO_BROWSER_CITATION_DIAGNOSIS_ONLY": "1" if diagnosis_only else "0", "VIDEO_BROWSER_CITATION_RESOURCE_PATH": "/acceptance/run/video-probe-resource.json" if diagnosis_only else "", "VIDEO_BROWSER_CITATION_RUN_OWNED": "true", "VIDEO_BROWSER_CITATION_RUN_ID": run_id, "VIDEO_BROWSER_CITATION_OWNER": _ACCEPTANCE_OWNER, "VIDEO_BROWSER_CITATION_COMPOSE_PROJECT": project, "VIDEO_BROWSER_CITATION_RUN_ROOT": "/acceptance/run", "VIDEO_BROWSER_CITATION_PROFILE_DIR": "/acceptance/run/browser-profile", "VIDEO_BROWSER_CITATION_MANIFEST_PATH": "/acceptance/run/manifest.json"})
        def browser_stage() -> None:
            invoked = _run(compose + ["run", "--no-deps", *[item for key, value in browser_env.items() if key.startswith("VIDEO_BROWSER_CITATION_") for item in ("-e", f"{key}={value}")], "browser"], env=browser_env, timeout=timeout)
            _write_redacted_command_output(workdir / "browser-runner-output.json", invoked, label="browser-citation-only")
            _reconcile_resource_lifecycle(manifest, env)
            try:
                manifest["browser_profile_final"] = _load_citation_probe_lifecycle(browser_evidence, run_id=run_id, owner=_ACCEPTANCE_OWNER, project=project)
                (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
            except ValueError:
                if invoked.returncode:
                    profile = manifest["browser_profile_final"]
                    assert isinstance(profile, dict)
                    profile["created"] = (workdir / "browser-profile").exists()
                    profile["used"] = profile["created"]
                    _write_citation_probe_failure_evidence(browser_evidence, run_id=run_id, owner=_ACCEPTANCE_OWNER, project=project, failure_class="browser-evidence-missing")
                    payload = json.loads(browser_evidence.read_text(encoding="utf-8"))
                    payload["browser_profile"] = dict(profile)
                    browser_evidence.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8")
                    manifest["browser_profile_final"] = _load_citation_probe_lifecycle(browser_evidence, run_id=run_id, owner=_ACCEPTANCE_OWNER, project=project)
                    (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
                else:
                    raise StageFailure("browser-lifecycle-evidence")
            if invoked.returncode:
                failure_class = _load_browser_failure_class(browser_evidence)
                raise StageFailure(failure_class)
            result["browser"] = _load_citation_probe_evidence(browser_evidence, run_id=run_id, owner=_ACCEPTANCE_OWNER, project=project)
            manifest["browser_profile_final"] = result["browser"]["browser_profile"]
            (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        if not _stage("browser-citation-only", browser_stage, stages): return result
        result["release_recommendation"] = "citation-probe-pass"
        return result
    finally:
        if manifest is not None and compose is not None:
            try:
                logs = _run(compose + ["logs", "--no-color", "--no-log-prefix"], env=env, timeout=60)
                _write_redacted_command_output(workdir / "service-logs.json", logs, label="run-owned-services")
            except Exception:
                pass
            cleanup_failed = False
            try:
                if not any(manifest["resources"].values()): manifest["resources"] = _owned_resources(str(manifest["project"]), str(manifest["run_id"]), env)
                if not isinstance(manifest.get("resource_lifecycle"), dict) or not any(
                    isinstance(item, dict) and item.get("created") for item in manifest["resource_lifecycle"].values()
                ):
                    _record_resource_lifecycle(manifest, env)
                _reconcile_resource_lifecycle(manifest, env)
                _cleanup_owned(manifest, env)
            except Exception: cleanup_failed = True
            try: _cleanup_owned_browser_profile(manifest, workdir)
            except Exception: cleanup_failed = True
            try:
                _finalize_resource_lifecycle(manifest, env)
            except Exception:
                cleanup_failed = True
            if browser_evidence.is_file():
                try:
                    manifest["browser_profile_final"] = _load_citation_probe_lifecycle(browser_evidence, run_id=str(manifest["run_id"]), owner=_ACCEPTANCE_OWNER, project=str(manifest["project"]))
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    pass
            profile = manifest.get("browser_profile_final")
            if isinstance(profile, dict):
                profile["cleaned"] = not (workdir / "browser-profile").exists()
            stages.append({"name": "cleanup", "outcome": "failed" if cleanup_failed else "passed", "duration_seconds": 0, "detail": "ownership-cleanup" if cleanup_failed else ""})
        artifact_cleanup_failed = False
        for transient in ("compose.env", "browser-accounts.json", "video-fixture.mp4", "video-probe-resource.json", "compatibility.txt", "compatibility.png", "compatibility.pdf", "pgvector-init.sql", "nginx.conf", "mock_provider.py", "video_browser_uat.mjs", "generate_compat_fixtures.py", "generate_video_fixture.py", "prepare_video_citation_probe.py", "legacy-browser-resource.json"):
            try:
                (workdir / transient).unlink(missing_ok=True)
            except OSError:
                artifact_cleanup_failed = True
        stages.append({"name": "artifact-cleanup", "outcome": "failed" if artifact_cleanup_failed else "passed", "duration_seconds": 0, "detail": "transient-cleanup" if artifact_cleanup_failed else ""})
        if foreign_before is not None:
            foreign_after = _docker_inventory(env)
            unchanged = foreign_after == foreign_before
            result["foreign_docker"] = {"before": foreign_before, "after": foreign_after, "unchanged": unchanged}
            stages.append({"name": "foreign-docker-inventory", "outcome": "passed" if unchanged else "failed", "duration_seconds": 0, "detail": "" if unchanged else "inventory-drift"})
        diagnosis_only = os.getenv("VIDEO_CITATION_DIAGNOSIS_ONLY") == "1"
        result["release_recommendation"] = ("citation-diagnosis-pass" if diagnosis_only else "citation-probe-pass") if result.get("browser") and all(stage["outcome"] == "passed" for stage in stages) else "not-releasable"
        if manifest is not None:
            (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
            (workdir / "owner-manifest-final.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        (workdir / "evidence.json").write_text(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")


def _compose_up_probe(compose: list[str], env: dict[str, str], timeout: int) -> None:
    if _run(compose + ["up", "-d", "postgres", "redis", "migrate", "mock-provider", "app", "nginx"], env=env, timeout=timeout).returncode:
        raise StageFailure("compose-up")


def run(target_id: str, workdir: Path, commit: str, *, video_fixture: Path | None = None, timeout: int = 180, phase_a: bool = False, upload_diagnosis: bool = False) -> dict[str, object]:
    _require_isolated_venv()
    target = _safe_target(target_id)
    revision = _require_clean_detached_commit(commit)
    identity = _verification_identity(revision, os.environ.copy())
    temp_root = Path(tempfile.gettempdir()).resolve()
    workdir = workdir.resolve()
    if temp_root not in workdir.parents or any(marker in str(workdir).lower() for marker in UNSAFE_MARKERS):
        raise ValueError("working directory must be an isolated descendant of the system temp directory")
    workdir.mkdir(parents=True, exist_ok=False)
    fixture: Path | None = None
    compose: list[str] | None = None
    env: dict[str, str] = {}
    manifest: dict[str, object] | None = None
    foreign_before: dict[str, dict[str, object]] | None = None
    evidence: list[dict[str, object]] = []
    test_failures: list[dict[str, str]] = []
    result: dict[str, object] = {
        "schema_version": 2,
        "target_id": target,
        "revision": revision,
        "identity": identity,
        "owner": _ACCEPTANCE_OWNER,
        "provider_mode": "mock",
        "non_production": True,
        "stages": evidence,
        "deferred": ["external-provider", "video", "browser-uat", "production-approval"],
    }
    if phase_a:
        result["phase"] = "A"
    video_stage_evidence = workdir / "video-stage-evidence.json"
    video_phase = workdir / "video-stage-phase.txt"
    browser_evidence = workdir / "browser-stage-evidence.json"
    fixture_evidence = workdir / "fixture-stage-evidence.json"
    legacy_browser_resource = workdir / "legacy-browser-resource.json"
    try:
        if video_fixture is not None:
            fixture = _stage_video_fixture(video_fixture, workdir)
        resource_token = secrets.token_hex(8)
        run_id = f"video54-full-{time.strftime('%Y%m%d')}-{revision[:7]}-{resource_token}"
        project = f"video54full_{resource_token}"
        port = str(18080 + secrets.randbelow(1000))
        pg_port = str(19080 + secrets.randbelow(1000))
        password = _secret()
        result.update({"run_id": run_id, "project": project})
        env = os.environ.copy()
        _require_local_docker(env)
        foreign_before = _docker_inventory(env)
        result["foreign_docker"] = {"before": foreign_before, "after": None, "unchanged": False}
        for key in ("DATABASE_URL", "POSTGRES_PASSWORD", "DEFAULT_ADMIN_PASSWORD", "JWT_SECRET", "JWT_REFRESH_SECRET"):
            env.pop(key, None)
        env.update({
            "ACCEPTANCE_RUN_ID": run_id, "ACCEPTANCE_OWNER": _ACCEPTANCE_OWNER, "ACCEPTANCE_RUN_DIR": str(workdir), "ACCEPTANCE_HTTP_PORT": port, "ACCEPTANCE_PG_PORT": pg_port,
            "ACCEPTANCE_APP_IMAGE": os.getenv("ACCEPTANCE_APP_IMAGE", ""),
            "ACCEPTANCE_APP_METADATA_PATH": os.getenv("ACCEPTANCE_APP_METADATA_PATH", ""),
            "ACCEPTANCE_FRONTEND_IMAGE": os.getenv("ACCEPTANCE_FRONTEND_IMAGE", ""),
            "ACCEPTANCE_FRONTEND_METADATA_PATH": os.getenv("ACCEPTANCE_FRONTEND_METADATA_PATH", ""),
            "ACCEPTANCE_POSTGRES_IMAGE": os.getenv("ACCEPTANCE_POSTGRES_IMAGE", "pgvector/pgvector:pg16"),
            "ACCEPTANCE_REDIS_IMAGE": os.getenv("ACCEPTANCE_REDIS_IMAGE", "redis:7-alpine"),
            "ACCEPTANCE_NGINX_IMAGE": os.getenv("ACCEPTANCE_NGINX_IMAGE", "nginx:alpine"),
            "ACCEPTANCE_BROWSER_IMAGE": os.getenv("ACCEPTANCE_BROWSER_IMAGE", ""),
            "ACCEPTANCE_BROWSER_METADATA_PATH": os.getenv("ACCEPTANCE_BROWSER_METADATA_PATH", ""),
            "POSTGRES_USER": "acceptance", "POSTGRES_PASSWORD": password, "POSTGRES_DATABASE": f"acceptance_{resource_token}",
            "DATABASE_URL": f"postgresql://acceptance:{password}@postgres:5432/acceptance_{resource_token}",
            "JWT_SECRET": _secret(), "JWT_REFRESH_SECRET": _secret(),
            "DEFAULT_ADMIN_USERNAME": "acceptance_admin", "DEFAULT_ADMIN_PASSWORD": _secret(),
        })
        if phase_a:
            env["VIDEO_BROWSER_PHASE_A"] = "1"
        if upload_diagnosis:
            env["VIDEO_BROWSER_UPLOAD_DIAGNOSIS"] = "1"
        required_image_inputs = (
            "ACCEPTANCE_APP_IMAGE", "ACCEPTANCE_APP_METADATA_PATH",
            "ACCEPTANCE_FRONTEND_IMAGE", "ACCEPTANCE_FRONTEND_METADATA_PATH",
            "ACCEPTANCE_BROWSER_IMAGE", "ACCEPTANCE_BROWSER_METADATA_PATH",
        )
        if any(not env[key] for key in required_image_inputs):
            raise ValueError("acceptance app and frontend image identity inputs are required")
        image = _require_image_revision(env["ACCEPTANCE_APP_IMAGE"], revision, env["ACCEPTANCE_APP_METADATA_PATH"], env)
        frontend_image = _require_image_revision(env["ACCEPTANCE_FRONTEND_IMAGE"], revision, env["ACCEPTANCE_FRONTEND_METADATA_PATH"], env)
        browser_image = _require_image_revision(env["ACCEPTANCE_BROWSER_IMAGE"], revision, env["ACCEPTANCE_BROWSER_METADATA_PATH"], env)
        result["image"] = image
        result["frontend_image"] = frontend_image
        result["browser_image"] = browser_image
        (workdir / "pgvector-init.sql").write_text((ROOT / "tests" / "acceptance" / "pgvector-init.sql").read_text(encoding="utf-8"), encoding="utf-8")
        (workdir / "nginx.conf").write_text((ROOT / "tests" / "acceptance" / "nginx.conf").read_text(encoding="utf-8"), encoding="utf-8")
        shutil.copy2(ROOT / "tests" / "acceptance" / "mock_video_provider.py", workdir / "mock_provider.py")
        shutil.copy2(ROOT / "tests" / "acceptance" / "video_browser_uat.mjs", workdir / "video_browser_uat.mjs")
        shutil.copy2(ROOT / "tests" / "acceptance" / "generate_compat_fixtures.py", workdir / "generate_compat_fixtures.py")
        shutil.copy2(ROOT / "tests" / "acceptance" / "generate_video_fixture.py", workdir / "generate_video_fixture.py")
        compose = ["docker", "compose", "-p", project, "--env-file", str(workdir / "compose.env"), "-f", str(COMPOSE)]
        (workdir / "compose.env").write_text("\n".join(f"{k}={v}" for k, v in env.items() if k.startswith("ACCEPTANCE_") or k in {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DATABASE", "DATABASE_URL", "JWT_SECRET", "JWT_REFRESH_SECRET", "DEFAULT_ADMIN_USERNAME", "DEFAULT_ADMIN_PASSWORD"}), encoding="utf-8")
        manifest = {
            "schema_version": 2,
            "run_id": run_id,
            "owner": _ACCEPTANCE_OWNER,
            "project": project,
            "revision": revision,
            "identity": identity,
            "provider_mode": "mock",
            "image": image,
            "frontend_image": frontend_image,
            "browser_image": browser_image,
            "resources": {"containers": [], "volumes": [], "networks": []},
            "resource_lifecycle": {kind: {"created": [], "removed": [], "remaining": [], "status_confirmed": False} for kind in ("containers", "volumes", "networks")},
            "artifacts": {"browser_profile": "browser-profile"},
            "browser_profile_initial": {"path": "browser-profile", "exists": False},
            "browser_profile_final": {"path": "browser-profile", "created": False, "used": False, "context_closed": False, "cleaned": False},
        }
        (workdir / "owner-manifest-initial.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        def compose_up():
            result = _run(compose + ["up", "-d", "postgres", "redis", "migrate", "mock-provider", "app", "nginx"], env=env, timeout=timeout)
            if result.returncode:
                raise RuntimeError("compose-up")
        if not _stage("compose-up", compose_up, evidence):
            return result | {"release_recommendation": "not-releasable"}
        manifest["resources"] = _owned_resources(project, run_id, env)
        _record_resource_lifecycle(manifest, env)
        (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        base = f"http://127.0.0.1:{port}"
        if not _stage("health", lambda: _wait_for_health(base), evidence):
            return result | {"release_recommendation": "not-releasable"}
        def fixture_stage() -> None:
            generated = _run(compose + ["run", "--no-deps", "fixture"], env=env, timeout=timeout)
            fixture_result = _load_fixture_stage_evidence(fixture_evidence, run_id=run_id, owner=_ACCEPTANCE_OWNER, service_exit_code=generated.returncode)
            result["fixture"] = fixture_result
            manifest["resources"] = _owned_resources(project, run_id, env)
            _reconcile_resource_lifecycle(manifest, env)
            (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
            if generated.returncode != fixture_result["fixture_service_exit_code"]:
                raise StageFailure("fixture-exit-mismatch")
            if generated.returncode:
                raise StageFailure(str(fixture_result["failure_class"] or "fixture-command"))
        if not _stage("video-fixture", fixture_stage, evidence):
            return result | {"release_recommendation": "not-releasable"}
        fixture = workdir / "video-fixture.mp4"
        if not fixture.is_file() or fixture.stat().st_size <= 0:
            raise RuntimeError("fixture-missing")
        fixture_summary = {"filename": fixture.name, "sha256": _sha256_file(fixture), "owned_by_run": True, "generated_by": "acceptance-fixture-service"}
        result["fixture"] = fixture_summary
        manifest["fixture"] = fixture_summary
        (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        if upload_diagnosis:
            browser_accounts = {"admin": {"username": env["DEFAULT_ADMIN_USERNAME"], "password": env["DEFAULT_ADMIN_PASSWORD"]}, "roles": []}
            (workdir / "browser-accounts.json").write_text(json.dumps(browser_accounts), encoding="utf-8")
            def upload_diagnosis_browser() -> None:
                profile_state = manifest["browser_profile_final"]
                profile_state["used"] = True
                (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
                browser = _run(compose + ["run", "--no-deps", "browser"], env=env, timeout=timeout)
                _write_diagnosis_command_output(workdir / "browser-runner-output.json", browser, label="browser-upload-diagnosis")
                _reconcile_resource_lifecycle(manifest, env)
                profile_state["created"] = (workdir / "browser-profile").exists()
                profile_state["context_closed"] = True
                if browser.returncode:
                    raise RuntimeError("browser-upload-diagnosis")
                result["browser"] = _load_upload_diagnosis_evidence(browser_evidence)
            if not _stage("browser-upload-diagnosis", upload_diagnosis_browser, evidence):
                return result
            result["release_recommendation"] = "upload-diagnosis-pass"
            return result
        if phase_a:
            # The representative Phase A path is intentionally UI-only: one
            # run-owned fixture, KB, Agent, thread, batch upload, and query.
            browser_accounts = {"admin": {"username": env["DEFAULT_ADMIN_USERNAME"], "password": env["DEFAULT_ADMIN_PASSWORD"]}, "roles": []}
            (workdir / "browser-accounts.json").write_text(json.dumps(browser_accounts), encoding="utf-8")
            def phase_a_browser_uat() -> None:
                profile_state = manifest["browser_profile_final"]
                assert isinstance(profile_state, dict)
                profile_state["used"] = True
                (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
                browser = _run(compose + ["run", "--no-deps", "browser"], env=env, timeout=timeout)
                _write_redacted_command_output(workdir / "browser-runner-output.json", browser, label="browser-phase-a")
                _reconcile_resource_lifecycle(manifest, env)
                profile_state["created"] = (workdir / "browser-profile").exists()
                profile_state["context_closed"] = True
                (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
                if browser.returncode:
                    result["browser_failure"] = _load_browser_failure_class(browser_evidence)
                    raise RuntimeError("browser-phase-a")
                result["browser"] = _load_phase_a_browser_evidence(browser_evidence)
            if not _stage("browser-phase-a", phase_a_browser_uat, evidence):
                return result
            result["release_recommendation"] = "phase-a-representative-pass" if all(item["outcome"] == "passed" for item in evidence) else "not-releasable"
            return result
        application_env, migration_env = _database_test_environments(env, password=password, pg_port=pg_port)
        def pytest_stage(nodeid: str, *, test_env: dict[str, str] = application_env):
            result = _run([sys.executable, "-m", "pytest", "-q", nodeid], env=test_env, timeout=timeout)
            if result.returncode:
                test_failures.append({"test": nodeid.rsplit("::", 1)[0].rsplit("/", 1)[-1], "class": _classify_pytest_failure(result)})
                raise RuntimeError(f"pytest-{nodeid}")
        migration_nodes = (
            ("migration-fresh", "tests/test_pg_migration_runner_integration.py::test_complete_chain_fresh_install_and_repeat"),
            ("migration-repeat", "tests/test_pg_migration_runner_integration.py::test_complete_chain_fresh_install_and_repeat"),
        )
        for name, nodeid in migration_nodes:
            if not _stage(name, lambda nodeid=nodeid: pytest_stage(nodeid, test_env=migration_env), evidence):
                return result | {"release_recommendation": "not-releasable"}
        migration_upgrade: dict[str, object] = {}
        def migration_upgrade_stage() -> None:
            migration_upgrade.update(_run_actual_migration_upgrade(workdir, migration_env, f"acceptance_upgrade_{resource_token}"))
            manifest["migration_upgrade"] = migration_upgrade
            (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        if not _stage("migration-upgrade", migration_upgrade_stage, evidence):
            return result | {"release_recommendation": "not-releasable"}
        def migration_history_checksum() -> None:
            verified = _run([sys.executable, "scripts/pg_migration_runner.py", "verify"], env=application_env, timeout=timeout)
            if verified.returncode or "pending=0" not in verified.stdout:
                raise RuntimeError("migration-history-checksum")
        if not _stage("migration-history-checksum", migration_history_checksum, evidence):
            return result | {"release_recommendation": "not-releasable"}
        if not _stage("migration-failure", lambda: pytest_stage("tests/test_pg_migration_runner_integration.py::test_failing_migration_stops_before_later_file", test_env=migration_env), evidence):
            return result | {"release_recommendation": "not-releasable"}
        if not _stage("roles", lambda: pytest_stage("tests/test_pg_authenticated_api_integration.py"), evidence):
            return result | {"release_recommendation": "not-releasable"}
        try:
            _fixed_runtime_stages(base, evidence)
        except RuntimeError:
            return result | {"release_recommendation": "not-releasable"}
        application_env.update({
            "VIDEO_ACCEPTANCE_BASE_URL": base,
            "VIDEO_ACCEPTANCE_FIXTURE": str(fixture),
            "VIDEO_ACCEPTANCE_DATABASE_URL": application_env["DATABASE_URL"],
            "VIDEO_ACCEPTANCE_COMPOSE": json.dumps(compose),
            "VIDEO_ACCEPTANCE_EVIDENCE_PATH": str(video_stage_evidence),
            "VIDEO_ACCEPTANCE_PHASE_PATH": str(video_phase),
            "VIDEO_ACCEPTANCE_RESTART_DURING_PROCESSING": "1",
            "VIDEO_ACCEPTANCE_LEGACY_RESOURCE_PATH": str(legacy_browser_resource),
        })
        def video_worker_sse():
            try:
                pytest_stage("tests/acceptance/test_video_worker_sse.py", test_env=application_env)
            except RuntimeError:
                result["video_failure_phase"] = _load_video_failure_phase(video_phase)
                raise
            result["video"] = _load_video_stage_evidence(video_stage_evidence)
            if not legacy_browser_resource.is_file() or legacy_browser_resource.stat().st_size > 4096:
                raise RuntimeError("legacy-browser-resource")
        if not _stage("video-worker-sse-recovery", video_worker_sse, evidence):
            return result
        result["deferred"].remove("video")
        def legacy_video_regression() -> None:
            pytest_stage("tests/test_video_automatic_uploads.py::test_worker_rejects_missing_video_profile_without_rewriting_snapshot")
            pytest_stage("tests/test_video_automatic_uploads.py::test_worker_rejects_retired_video_profiles_without_probe")
        if not _stage("legacy-video-regression", legacy_video_regression, evidence):
            return result
        result["legacy_video_regression"] = True
        browser_accounts = {
            "admin": {"username": env["DEFAULT_ADMIN_USERNAME"], "password": env["DEFAULT_ADMIN_PASSWORD"]},
            "roles": [
                {"role": role, "username": f"v{run_id}{index}", "initial_password": f"Aa1!{_secret()}", "password": f"Bb2!{_secret()}"}
                for index, role in enumerate(("super_admin", "dept_admin", "teacher", "assistant", "student"), start=1)
            ],
        }
        (workdir / "browser-accounts.json").write_text(json.dumps(browser_accounts), encoding="utf-8")
        def browser_uat() -> None:
            profile_state = manifest["browser_profile_final"]
            assert isinstance(profile_state, dict)
            profile_state["used"] = True
            (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
            browser = _run(compose + ["run", "--no-deps", "browser"], env=env, timeout=timeout)
            _reconcile_resource_lifecycle(manifest, env)
            profile_state["created"] = (workdir / "browser-profile").exists()
            profile_state["context_closed"] = True
            (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
            if browser.returncode:
                result["browser_failure"] = _load_browser_failure_class(browser_evidence)
                raise RuntimeError("browser-phase-a" if phase_a else "browser-uat")
            result["browser"] = _load_phase_a_browser_evidence(browser_evidence) if phase_a else _load_browser_stage_evidence(browser_evidence)
        browser_stage_name = "browser-phase-a" if phase_a else "browser-uat"
        if not _stage(browser_stage_name, browser_uat, evidence):
            return result
        if not phase_a:
            result["deferred"].remove("browser-uat")
        result["release_recommendation"] = ("phase-a-representative-pass" if phase_a else "isolated-non-production-5.4-pass") if all(x["outcome"] == "passed" for x in evidence) else "not-releasable"
        return result
    finally:
        if compose is not None and manifest is not None:
            cleanup_failed = False
            try:
                service_logs = _run(compose + ["logs", "--no-color", "--timestamps"], env=env, timeout=60)
                if upload_diagnosis:
                    _write_diagnosis_command_output(workdir / "service-logs.json", service_logs, label="compose-service-logs")
                else:
                    _write_redacted_command_output(workdir / "service-logs.json", service_logs, label="compose-service-logs")
            except Exception:
                cleanup_failed = True
            try:
                if not any(manifest["resources"].values()):
                    manifest["resources"] = _owned_resources(str(manifest["project"]), str(manifest["run_id"]), env)
                    (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
                _cleanup_owned(manifest, env)
                _finalize_resource_lifecycle(manifest, env)
            except Exception:
                cleanup_failed = True
            try:
                _cleanup_owned_browser_profile(manifest, workdir)
            except Exception:
                cleanup_failed = True
            profile_state = manifest.get("browser_profile_final")
            if isinstance(profile_state, dict):
                profile_state["cleaned"] = not (workdir / "browser-profile").exists()
            if cleanup_failed:
                evidence.append({"name": "cleanup", "outcome": "failed", "duration_seconds": 0, "detail": "ownership-cleanup"})
            else:
                evidence.append({"name": "cleanup", "outcome": "passed", "duration_seconds": 0, "detail": ""})
        cleanup_ok = True
        transient_paths = [workdir / name for name in ("compose.env", "pgvector-init.sql", "nginx.conf", "mock_provider.py", "video_browser_uat.mjs", "generate_compat_fixtures.py", "generate_video_fixture.py", "browser-accounts.json", "legacy-browser-resource.json", "video-stage-evidence.json", "video-stage-phase.txt", "fixture-stage-evidence.json", "video-fixture.mp4", "compatibility.txt", "compatibility.png", "compatibility.pdf")]
        if fixture is not None:
            transient_paths.append(fixture)
        for transient in transient_paths:
            try:
                transient.unlink(missing_ok=True)
            except OSError:
                cleanup_ok = False
        upgrade_root = workdir / "migration-upgrade-root"
        try:
            if upgrade_root.exists():
                shutil.rmtree(upgrade_root)
        except OSError:
            cleanup_ok = False
        if not cleanup_ok:
            evidence.append({"name": "artifact-cleanup", "outcome": "failed", "duration_seconds": 0, "detail": "transient-cleanup"})
        fixture_stages = result.get("fixture_stages")
        if isinstance(fixture_stages, list):
            fixture_stages.append({"name": "cleanup", "outcome": "passed" if cleanup_ok else "failed", "exit_code": 0 if cleanup_ok else 1, "duration_seconds": 0, "failure_class": "" if cleanup_ok else "transient-cleanup"})
        if foreign_before is not None:
            try:
                foreign_after = _docker_inventory(env)
                unchanged = foreign_after == foreign_before
                result["foreign_docker"] = {
                    "before": _docker_inventory_summary(foreign_before),
                    "after": _docker_inventory_summary(foreign_after),
                    "unchanged": unchanged,
                }
                evidence.append({"name": "foreign-docker-inventory", "outcome": "passed" if unchanged else "failed", "duration_seconds": 0, "detail": "" if unchanged else "inventory-drift"})
            except Exception:
                result["foreign_docker"] = {
                    "before": _docker_inventory_summary(foreign_before),
                    "after": None,
                    "unchanged": False,
                }
                evidence.append({"name": "foreign-docker-inventory", "outcome": "failed", "duration_seconds": 0, "detail": "inventory-unavailable"})
        if upload_diagnosis:
            browser_stage_name = "browser-upload-diagnosis"
            browser_stage_passed = any(stage.get("name") == browser_stage_name and stage.get("outcome") == "passed" for stage in evidence)
            passed = browser_stage_passed and isinstance(result.get("browser"), dict) and result["browser"].get("complete") is True and all(stage["outcome"] == "passed" for stage in evidence)
            result["release_recommendation"] = "upload-diagnosis-pass" if passed else "not-releasable"
        else:
            browser_stage_name = "browser-phase-a" if phase_a else "browser-uat"
            browser_stage_passed = any(stage.get("name") == browser_stage_name and stage.get("outcome") == "passed" for stage in evidence)
            browser_evidence_present = browser_evidence.is_file()
            browser_evidence_complete = isinstance(result.get("browser"), dict) and result["browser"].get("complete") is True
            passed = bool(result.get("video")) and result.get("legacy_video_regression") is True and browser_stage_passed and browser_evidence_present and browser_evidence_complete and all(stage["outcome"] == "passed" for stage in evidence)
        if test_failures:
            result["test_failures"] = test_failures
        if not upload_diagnosis:
            result["release_recommendation"] = ("phase-a-representative-pass" if phase_a else "isolated-non-production-5.4-pass") if passed else "not-releasable"
        if manifest is not None:
            (workdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
            (workdir / "owner-manifest-final.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        (workdir / "evidence.json").write_text(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        (workdir / "runner-output.json").write_text(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--non-production", action="store_true", required=True)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--working-dir", type=Path, required=True)
    parser.add_argument("--video-fixture", type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--navigation-only", action="store_true")
    modes.add_argument("--citation-only", action="store_true")
    modes.add_argument("--citation-diagnosis", action="store_true")
    modes.add_argument("--phase-a-representative", action="store_true")
    modes.add_argument("--upload-diagnosis", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not args.non_production: raise ValueError("--non-production is required")
        if args.navigation_only:
            result = run_navigation_probe(args.target_id, args.working_dir, args.commit, timeout=240)
        elif args.citation_only or args.citation_diagnosis:
            if args.citation_diagnosis:
                os.environ["VIDEO_CITATION_DIAGNOSIS_ONLY"] = "1"
            result = run_citation_probe(args.target_id, args.working_dir, args.commit, timeout=900)
        elif args.upload_diagnosis:
            result = run(args.target_id, args.working_dir, args.commit, video_fixture=args.video_fixture, timeout=900, upload_diagnosis=True)
        elif args.phase_a_representative:
            result = run(args.target_id, args.working_dir, args.commit, video_fixture=args.video_fixture, timeout=900, phase_a=True)
        else:
            result = run(args.target_id, args.working_dir, args.commit, video_fixture=args.video_fixture, timeout=900)
    except Exception as exc:
        result = {"schema_version": 1, "release_recommendation": "not-releasable", "failure_class": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result.get("release_recommendation") in {"isolated-non-production-5.4-pass", "phase-a-representative-pass", "navigation-probe-pass", "citation-probe-pass", "citation-diagnosis-pass", "upload-diagnosis-pass"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
