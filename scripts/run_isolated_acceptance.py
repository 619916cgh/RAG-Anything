#!/usr/bin/env python3
"""Run the fixed disposable Compose acceptance profile.

This command owns the Compose project, credentials, temporary files, and cleanup.
It never accepts arbitrary stage commands and never reads the repository .env.
"""
from __future__ import annotations

import argparse
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
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "tests" / "acceptance" / "compose.yml"
ISOLATED_MARKERS = ("staging", "preprod", "acceptance", "ci", "test")
UNSAFE_MARKERS = ("production", "live")
_LOCAL_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\|file://|/(?:app|tmp|var|home|Users|uploads)(?:[\\/]|$))",
    re.IGNORECASE,
)


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


def _load_video_stage_evidence(path: Path) -> dict[str, object]:
    """Validate the small, path-free summary emitted by the video pytest stage."""
    if not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError("video stage evidence is missing or oversized")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("video stage evidence schema is invalid")
    video = payload.get("video")
    if not isinstance(video, dict) or set(video) != {"probe", "asset", "segment_count", "time_ranges"}:
        raise ValueError("video stage evidence fields are invalid")
    probe, asset, ranges = video["probe"], video["asset"], video["time_ranges"]
    if not isinstance(probe, dict) or not isinstance(asset, dict) or not isinstance(ranges, list):
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
    }
    if _LOCAL_PATH_RE.search(json.dumps(sanitized, ensure_ascii=True)):
        raise ValueError("video stage evidence contains a local path")
    return sanitized


def _load_video_failure_phase(path: Path) -> str:
    allowed = {
        "container-probe", "login", "kb-create", "upload", "task-poll",
        "retrieval-health", "storage-probe", "segment-validation", "agent-create",
        "sse", "media-range", "ungranted-user", "evidence-write",
    }
    try:
        phase = path.read_text(encoding="ascii").strip()
    except OSError:
        return "unknown"
    return phase if phase in allowed else "unknown"


def run(target_id: str, workdir: Path, commit: str, *, video_fixture: Path, timeout: int = 180) -> dict[str, object]:
    target = _safe_target(target_id)
    revision = _require_clean_detached_commit(commit)
    temp_root = Path(tempfile.gettempdir()).resolve()
    workdir = workdir.resolve()
    if temp_root not in workdir.parents or any(marker in str(workdir).lower() for marker in UNSAFE_MARKERS):
        raise ValueError("working directory must be an isolated descendant of the system temp directory")
    workdir.mkdir(parents=True, exist_ok=False)
    fixture: Path | None = None
    compose: list[str] | None = None
    evidence: list[dict[str, object]] = []
    result: dict[str, object] = {"schema_version": 1, "target_id": target, "revision": revision, "non_production": True, "stages": evidence, "deferred": ["external-provider", "video", "browser-uat", "production-approval"]}
    video_stage_evidence = workdir / "video-stage-evidence.json"
    video_phase = workdir / "video-stage-phase.txt"
    try:
        fixture = _stage_video_fixture(video_fixture, workdir)
        run_id = secrets.token_hex(8)
        project = f"ragaccept_{run_id}"
        port = str(18080 + secrets.randbelow(1000))
        pg_port = str(19080 + secrets.randbelow(1000))
        password = _secret()
        result.update({"run_id": run_id, "project": project})
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
        shutil.copy2(ROOT / "tests" / "acceptance" / "mock_video_provider.py", workdir / "mock_provider.py")
        compose = ["docker", "compose", "-p", project, "--env-file", str(workdir / "compose.env"), "-f", str(COMPOSE)]
        (workdir / "compose.env").write_text("\n".join(f"{k}={v}" for k, v in env.items() if k.startswith("ACCEPTANCE_") or k in {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DATABASE", "DATABASE_URL", "JWT_SECRET", "JWT_REFRESH_SECRET", "DEFAULT_ADMIN_USERNAME", "DEFAULT_ADMIN_PASSWORD"}), encoding="utf-8")
        def compose_up():
            result = _run(compose + ["up", "-d"], env=env, timeout=timeout)
            if result.returncode:
                raise RuntimeError("compose-up")
        if not _stage("compose-up", compose_up, evidence):
            return result | {"release_recommendation": "not-releasable"}
        base = f"http://127.0.0.1:{port}"
        if not _stage("health", lambda: _wait_for_health(base), evidence):
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
        stage_env.update({
            "VIDEO_ACCEPTANCE_BASE_URL": base,
            "VIDEO_ACCEPTANCE_FIXTURE": str(fixture),
            "VIDEO_ACCEPTANCE_DATABASE_URL": stage_env["DATABASE_URL"],
            "VIDEO_ACCEPTANCE_COMPOSE": json.dumps(compose),
            "VIDEO_ACCEPTANCE_EVIDENCE_PATH": str(video_stage_evidence),
            "VIDEO_ACCEPTANCE_PHASE_PATH": str(video_phase),
        })
        def video_worker_sse():
            try:
                pytest_stage("tests/acceptance/test_video_worker_sse.py")
            except RuntimeError:
                result["video_failure_phase"] = _load_video_failure_phase(video_phase)
                raise
            result["video"] = _load_video_stage_evidence(video_stage_evidence)
        if not _stage("video-worker-sse", video_worker_sse, evidence):
            return result
        result["deferred"].remove("video")
        result["release_recommendation"] = "isolated-preproduction-pass" if all(x["outcome"] == "passed" for x in evidence) else "not-releasable"
        return result
    finally:
        if compose is not None:
            cleanup = _run(compose + ["down", "--volumes", "--remove-orphans"], env=env, timeout=timeout)
            evidence.append({"name": "cleanup", "outcome": "passed" if cleanup.returncode == 0 else "failed", "duration_seconds": 0, "detail": "" if cleanup.returncode == 0 else "compose-cleanup"})
        cleanup_ok = True
        transient_paths = [workdir / name for name in ("compose.env", "pgvector-init.sql", "nginx.conf", "mock_provider.py", "video-stage-evidence.json", "video-stage-phase.txt")]
        if fixture is not None:
            transient_paths.append(fixture)
        for transient in transient_paths:
            try:
                transient.unlink(missing_ok=True)
            except OSError:
                cleanup_ok = False
        if not cleanup_ok:
            evidence.append({"name": "artifact-cleanup", "outcome": "failed", "duration_seconds": 0, "detail": "transient-cleanup"})
        passed = bool(result.get("video")) and all(stage["outcome"] == "passed" for stage in evidence)
        result["release_recommendation"] = "isolated-preproduction-pass" if passed else "not-releasable"
        (workdir / "evidence.json").write_text(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--non-production", action="store_true", required=True)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--working-dir", type=Path, required=True)
    parser.add_argument("--video-fixture", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if not args.non_production: raise ValueError("--non-production is required")
        result = run(args.target_id, args.working_dir, args.commit, video_fixture=args.video_fixture, timeout=900)
    except Exception as exc:
        result = {"schema_version": 1, "release_recommendation": "not-releasable", "failure_class": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result.get("release_recommendation") == "isolated-preproduction-pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
