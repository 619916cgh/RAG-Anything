#!/usr/bin/env python3
"""Read-only release-candidate ownership inventory for dirty worktrees."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Iterable


SHARED_PATHS = {
    "PROJECT_SUMMARY.md",
    "migrations/migration_manifest.json",
    "docker-compose.yml",
    "Dockerfile",
    "nginx.conf",
}
SHARED_PREFIXES = ("deploy/", ".github/workflows/")
GENERATED_PREFIXES = (".tmp-", "frontend/dist/", "__pycache__/")


def _git(root: Path, *args: str) -> str:
    """Run only read-only Git subcommands and return UTF-8 output."""
    result = subprocess.run(
        ["git", *args], cwd=root, check=True, text=True,
        encoding="utf-8", errors="replace", capture_output=True,
    )
    return result.stdout


def dirty_paths(root: Path) -> set[str]:
    paths: set[str] = set()
    for line in _git(root, "status", "--porcelain=v1", "--untracked-files=all").splitlines():
        if len(line) >= 4:
            paths.add(line[3:].replace("\\", "/"))
    return paths


def active_change_roots(root: Path) -> dict[str, str]:
    changes = root / "openspec" / "changes"
    if not changes.is_dir():
        return {}
    return {
        f"openspec/changes/{entry.name}/": entry.name
        for entry in changes.iterdir()
        if entry.is_dir() and entry.name != "archive"
    }


def classify_path(path: str, changes: dict[str, str]) -> dict[str, str]:
    normalized = path.replace("\\", "/")
    if normalized in SHARED_PATHS or normalized.startswith(SHARED_PREFIXES):
        return {"path": normalized, "classification": "shared", "owner": "coordinator"}
    for prefix, owner in changes.items():
        if normalized.startswith(prefix):
            return {"path": normalized, "classification": "owned", "owner": owner}
    if normalized.startswith(GENERATED_PREFIXES):
        return {"path": normalized, "classification": "generated-candidate", "owner": ""}
    return {"path": normalized, "classification": "unowned", "owner": ""}


def inventory(root: Path) -> dict[str, object]:
    root = root.resolve()
    changes = active_change_roots(root)
    entries = [classify_path(path, changes) for path in sorted(dirty_paths(root))]
    summary = {
        status: sum(1 for entry in entries if entry["classification"] == status)
        for status in ("owned", "shared", "unowned", "generated-candidate")
    }
    return {
        "schema_version": 1,
        "read_only": True,
        "entries": entries,
        "summary": summary,
        "warnings": [
            "Shared assets require serialized coordination.",
            "This inventory never stages, commits, resets, checks out, deletes, or moves files.",
        ],
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    print(json.dumps(inventory(args.root), ensure_ascii=True, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
