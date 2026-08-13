#!/usr/bin/env python3
"""Run explicit, isolated release acceptance checks and write safe evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import time
import urllib.request
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    from scripts.pg_migration_runner import sanitize_failure
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from pg_migration_runner import sanitize_failure


REQUIRED_STAGES = (
    "migration-fresh",
    "migration-upgrade",
    "migration-repeat",
    "migration-failure",
    "roles",
    "worker",
)
UNSAFE_MARKERS = ("production", "prod", "live")
ISOLATED_MARKERS = ("staging", "preprod", "acceptance", "ci", "test")
_ABSOLUTE_PATH = re.compile(r"(?:(?:[A-Za-z]:[\\/])|/)[^\s\"']+")


class AcceptanceError(RuntimeError):
    pass


def sanitize_evidence_detail(value: str) -> str:
    """Keep a bounded error class without leaking local paths or secrets."""
    return _ABSOLUTE_PATH.sub("<path>", sanitize_failure(value))


def _safe_identifier(value: str) -> str:
    value = str(value or "").strip().lower()
    if not value or any(marker in value for marker in UNSAFE_MARKERS):
        raise AcceptanceError("target identifier is missing or appears to be production")
    if not any(marker in value for marker in ISOLATED_MARKERS):
        raise AcceptanceError("target identifier must include an isolated environment marker")
    return value


def _safe_working_dir(value: Path) -> Path:
    resolved = value.resolve()
    text = resolved.as_posix().lower()
    if not any(marker in text for marker in ISOLATED_MARKERS):
        raise AcceptanceError("working directory must include an isolated environment marker")
    return resolved


def _parse_stage(value: str) -> tuple[str, list[str]]:
    name, separator, command = value.partition("=")
    if not separator or name not in REQUIRED_STAGES or not command.strip():
        raise AcceptanceError(
            "stage must be one of migration-fresh, migration-upgrade, "
            "migration-repeat, migration-failure, roles, or worker"
        )
    return name, shlex.split(command, posix=False)


def _parse_cleanup(value: str) -> list[str]:
    command = shlex.split(str(value or ""), posix=False)
    if not command:
        raise AcceptanceError("--cleanup-command is required")
    return command


def _stage_result(name: str, command: list[str], cwd: Path) -> dict[str, object]:
    started = time.monotonic()
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "name": name,
            "outcome": "failed",
            "duration_seconds": round(time.monotonic() - started, 3),
            "failure_class": "command-unavailable",
            "detail": sanitize_evidence_detail(str(exc)),
        }
    detail = sanitize_evidence_detail(result.stderr or result.stdout)
    return {
        "name": name,
        "outcome": "passed" if result.returncode == 0 else "failed",
        "duration_seconds": round(time.monotonic() - started, 3),
        "failure_class": "" if result.returncode == 0 else f"exit-{result.returncode}",
        "detail": "" if result.returncode == 0 else detail,
    }


def _health_result(url: str) -> dict[str, object]:
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            passed = 200 <= response.status < 300
            status = response.status
    except Exception as exc:
        passed = False
        status = None
        detail = sanitize_evidence_detail(str(exc))
    else:
        detail = "" if passed else f"http-{status}"
    return {
        "name": "health", "outcome": "passed" if passed else "failed",
        "duration_seconds": round(time.monotonic() - started, 3),
        "failure_class": "" if passed else "health-unavailable",
        "detail": detail,
        "http_status": status,
    }


def manifest_hash(root: Path) -> str:
    return hashlib.sha256((root / "migrations" / "migration_manifest.json").read_bytes()).hexdigest()


def repository_revision(root: Path) -> str:
    """Return only the immutable revision identifier for evidence."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
            text=True, encoding="utf-8", errors="replace", check=False,
        )
    except OSError:
        return "unknown"
    revision = result.stdout.strip()
    return revision if re.fullmatch(r"[0-9a-f]{40}", revision) else "unknown"


def _skipped_stage(name: str, reason: str) -> dict[str, object]:
    return {
        "name": name,
        "outcome": "skipped",
        "duration_seconds": 0,
        "failure_class": "required-stage-skipped",
        "detail": reason,
    }


def run_acceptance(args: argparse.Namespace) -> dict[str, object]:
    if not args.non_production:
        raise AcceptanceError("--non-production is required")
    _safe_identifier(args.target_id)
    _safe_working_dir(args.working_dir)
    repo_root = args.repo_root.resolve()
    if not (repo_root / "migrations" / "migration_manifest.json").is_file():
        raise AcceptanceError("repo root must contain migrations/migration_manifest.json")
    stage_commands = dict(_parse_stage(value) for value in args.stage_command)
    cleanup_command = _parse_cleanup(args.cleanup_command)
    missing = set(REQUIRED_STAGES) - set(stage_commands)
    if missing:
        raise AcceptanceError(f"required stages missing: {','.join(sorted(missing))}")

    stages: list[dict[str, object]] = []
    failure_reason = ""
    for name in (*REQUIRED_STAGES[:4], "health", *REQUIRED_STAGES[4:]):
        if failure_reason:
            stages.append(_skipped_stage(name, failure_reason))
            continue
        stage = (
            _health_result(args.health_url)
            if name == "health"
            else _stage_result(name, stage_commands[name], repo_root)
        )
        stages.append(stage)
        if stage["outcome"] != "passed":
            failure_reason = f"blocked after {name} did not pass"
    stages.append(_stage_result("cleanup", cleanup_command, args.working_dir.resolve()))
    passed = all(stage["outcome"] == "passed" for stage in stages)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_id": args.target_id,
        "non_production": True,
        "revision": repository_revision(repo_root),
        "manifest_sha256": manifest_hash(repo_root),
        "stages": stages,
        "release_recommendation": "isolated-preproduction-pass" if passed else "not-releasable",
        "deferred": ["external-provider", "video", "browser-uat", "production-approval"],
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--non-production", action="store_true")
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--working-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--health-url", required=True)
    parser.add_argument("--stage-command", action="append", default=[])
    parser.add_argument("--cleanup-command", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        evidence = run_acceptance(args)
    except AcceptanceError as exc:
        evidence = {"schema_version": 1, "release_recommendation": "not-releasable", "failure_class": "target-guard", "detail": sanitize_evidence_detail(str(exc))}
    args.evidence.write_text(json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if evidence.get("release_recommendation") == "isolated-preproduction-pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
