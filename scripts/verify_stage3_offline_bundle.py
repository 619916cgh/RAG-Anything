#!/usr/bin/env python3
"""Read-only verifier for a Stage 3 offline release bundle.

It never loads images, starts Compose, reads dotenv files, or contacts a
network endpoint.  Results intentionally contain only fixed codes, status,
and checksums so they are safe to attach to an offline release record.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Any, Iterable

SHA = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
VARNAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
DEFAULT_SUMS_SHA256 = "b7576624c7ed2cb1eddcc151b4681501ee726dc48929ea75f5e8b99309150d41"
REQUIRED_ARCHIVES = {"candidate", "rollback", "postgres", "redis", "nginx"}


class VerifyError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_member(member: tarfile.TarInfo) -> bool:
    name = member.name.replace("\\", "/")
    if not name or name.startswith("/") or ".." in Path(name).parts:
        return False
    if member.issym() or member.islnk():
        target = member.linkname.replace("\\", "/")
        return bool(target) and not target.startswith("/") and ".." not in Path(target).parts
    return True


def _read_json(tar: tarfile.TarFile, member: str) -> dict[str, Any]:
    item = tar.extractfile(member)
    if item is None:
        raise VerifyError("E_OCI_LAYOUT")
    try:
        value = json.load(item)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise VerifyError("E_OCI_LAYOUT") from exc
    if not isinstance(value, dict):
        raise VerifyError("E_OCI_LAYOUT")
    return value


def _verify_image_archive(path: Path, expected: dict[str, Any]) -> None:
    try:
        with tarfile.open(path, "r") as archive:
            members = archive.getmembers()
            if not members or any(not _safe_member(member) for member in members):
                raise VerifyError("E_ARCHIVE_PATH")
            # ``docker save`` writes an OCI index alongside the legacy
            # manifest.json.  The identity manifest records the immutable
            # index/manifest descriptor digest (the value returned by
            # ``docker image inspect .Id`` for a multi-platform image), not
            # the config blob digest in manifest.json.  Verify that complete
            # descriptor chain before inspecting the config labels.
            index_raw = archive.extractfile("index.json")
            if index_raw is None:
                raise VerifyError("E_OCI_LAYOUT")
            index = json.load(index_raw)
            descriptors = index.get("manifests") if isinstance(index, dict) else None
            if not isinstance(descriptors, list) or not descriptors:
                raise VerifyError("E_OCI_LAYOUT")
            expected_digest = str(expected.get("digest", ""))
            descriptor = next((item for item in descriptors if isinstance(item, dict) and item.get("digest") == expected_digest), None)
            if descriptor is None:
                raise VerifyError("E_OCI_DIGEST")
            descriptor_path = "blobs/" + expected_digest.replace(":", "/")
            descriptor_blob = archive.extractfile(descriptor_path)
            if descriptor_blob is None:
                raise VerifyError("E_OCI_LAYOUT")
            descriptor_bytes = descriptor_blob.read()
            if "sha256:" + hashlib.sha256(descriptor_bytes).hexdigest() != expected_digest:
                raise VerifyError("E_OCI_DIGEST")
            descriptor_json = json.loads(descriptor_bytes)
            manifest_descriptors = descriptor_json.get("manifests") if isinstance(descriptor_json, dict) else None
            if not isinstance(manifest_descriptors, list):
                manifest_descriptors = [descriptor_json]
            platform_matches = [item for item in manifest_descriptors if isinstance(item, dict) and item.get("platform", {}).get("os") == "linux" and item.get("platform", {}).get("architecture") == "amd64"]
            if not platform_matches:
                raise VerifyError("E_OCI_PLATFORM")
            child_digest = platform_matches[0].get("digest")
            child_path = "blobs/" + str(child_digest).replace(":", "/")
            child_blob = archive.extractfile(child_path)
            if child_blob is None or "sha256:" + hashlib.sha256(child_blob.read()).hexdigest() != child_digest:
                raise VerifyError("E_OCI_DIGEST")
            index_file = archive.extractfile("manifest.json")
            if index_file is None:
                raise VerifyError("E_OCI_LAYOUT")
            index = json.load(index_file)
            if not isinstance(index, list) or len(index) != 1 or not isinstance(index[0], dict):
                raise VerifyError("E_OCI_LAYOUT")
            entry = index[0]
            config_name = entry.get("Config")
            tags = entry.get("RepoTags") or []
            if not isinstance(config_name, str) or expected.get("reference") not in tags:
                raise VerifyError("E_OCI_REFERENCE")
            raw = archive.extractfile(config_name)
            if raw is None:
                raise VerifyError("E_OCI_LAYOUT")
            config_bytes = raw.read()
            config = json.loads(config_bytes)
    except (tarfile.TarError, OSError, json.JSONDecodeError) as exc:
        raise VerifyError("E_OCI_LAYOUT") from exc
    labels = (config.get("config") or {}).get("Labels") or {}
    if f"{config.get('os')}/{config.get('architecture')}" != "linux/amd64":
        raise VerifyError("E_OCI_PLATFORM")
    revision = expected.get("revision")
    if revision and labels.get("org.opencontainers.image.revision") != revision:
        raise VerifyError("E_OCI_REVISION")


def _checksums(bundle: Path, sums: Path) -> set[str]:
    listed: set[str] = set()
    try:
        lines = sums.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise VerifyError("E_SUMS_FORMAT") from exc
    for line in lines:
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise VerifyError("E_SUMS_FORMAT") from exc
        relative_path = Path(relative)
        if not SHA.fullmatch(digest) or relative_path.is_absolute() or ".." in relative_path.parts or relative in listed:
            raise VerifyError("E_SUMS_FORMAT")
        target = bundle / relative_path
        if target.is_symlink() or not target.is_file() or checksum(target) != digest:
            raise VerifyError("E_SUMS_MISMATCH")
        listed.add(relative)
    actual: set[str] = set()
    for entry in bundle.rglob("*"):
        if entry.is_symlink():
            raise VerifyError("E_SYMLINK")
        if entry.is_file() and entry != sums:
            actual.add(entry.relative_to(bundle).as_posix())
    if listed != actual:
        raise VerifyError("E_ALLOWLIST")
    return listed


def _verify_migrations(bundle: Path, migration: dict[str, Any]) -> None:
    manifest_path = bundle / str(migration.get("manifest_path", ""))
    if not manifest_path.is_file() or checksum(manifest_path) != migration.get("manifest_sha256"):
        raise VerifyError("E_MIGRATION_MANIFEST")
    entries = migration.get("sql_checksums")
    if not isinstance(entries, list) or not entries:
        raise VerifyError("E_MIGRATION_MANIFEST")
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise VerifyError("E_MIGRATION_MANIFEST")
        sql = manifest_path.parent / item["id"]
        if not sql.is_file() or checksum(sql) != item.get("sha256"):
            raise VerifyError("E_MIGRATION_CHECKSUM")


def _verify_git(git_root: Path | None, candidate: str, rollback: str) -> None:
    if git_root is None:
        return
    def call(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=git_root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if any(call("cat-file", "-e", f"{value}^{{commit}}").returncode for value in (candidate, rollback)):
        raise VerifyError("E_GIT_OBJECT")
    if call("merge-base", "--is-ancestor", rollback, candidate).returncode:
        raise VerifyError("E_GIT_ANCESTRY")


def verify(bundle: Path, *, expected_sums_sha256: str = DEFAULT_SUMS_SHA256, git_root: Path | None = None) -> dict[str, Any]:
    bundle = bundle.resolve()
    sums = bundle / "SHA256SUMS"
    if not bundle.is_dir() or not sums.is_file():
        raise VerifyError("E_BUNDLE_ROOT")
    if expected_sums_sha256 and checksum(sums) != expected_sums_sha256.lower():
        raise VerifyError("E_SUMS_SELF")
    _checksums(bundle, sums)
    try:
        identity = json.loads((bundle / "manifests" / "oci-identity.json").read_text(encoding="utf-8"))
        migration = json.loads((bundle / "manifests" / "migration.json").read_text(encoding="utf-8"))
        deploy = json.loads((bundle / "manifests" / "deploy-script-checksums.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerifyError("E_MANIFEST") from exc
    candidate, rollback = identity.get("candidate", {}), identity.get("rollback", {})
    if not identity.get("non_production") or not all(isinstance(x, dict) for x in (candidate, rollback)):
        raise VerifyError("E_IDENTITY")
    if not GIT_SHA.fullmatch(str(candidate.get("revision", ""))) or not GIT_SHA.fullmatch(str(rollback.get("revision", ""))):
        raise VerifyError("E_GIT_SHA")
    if identity.get("ancestry", {}).get("rollback_is_candidate_ancestor") is not True:
        raise VerifyError("E_GIT_ANCESTRY")
    _verify_git(git_root, candidate["revision"], rollback["revision"])
    for name in REQUIRED_ARCHIVES:
        archive = bundle / "images" / f"{name}.tar"
        expected = candidate if name == "candidate" else rollback if name == "rollback" else identity.get("dependencies", {}).get(name, {})
        if not archive.is_file() or not isinstance(expected, dict):
            raise VerifyError("E_IMAGE_INVENTORY")
        _verify_image_archive(archive, expected)
    _verify_migrations(bundle, migration)
    for relative, value in deploy.items():
        target = bundle / "source" / "static" / relative
        if not isinstance(relative, str) or not SHA.fullmatch(str(value)) or not target.is_file() or checksum(target) != value:
            raise VerifyError("E_DEPLOY_SCRIPT")
    secret_refs = bundle / "requirements" / "secret-references.txt"
    if not secret_refs.is_file() or any(not VARNAME.fullmatch(line) for line in secret_refs.read_text(encoding="utf-8").splitlines() if line):
        raise VerifyError("E_SECRET_REFERENCE")
    if not (bundle / "runbook.md").is_file() or not (bundle / "post-deploy-acceptance-checklist.md").is_file():
        raise VerifyError("E_RUNBOOK")
    return {"status": "passed", "code": "OK", "bundle_sha256sums": checksum(sums), "files": len(_checksums(bundle, sums)) + 1}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--git-root", type=Path)
    parser.add_argument("--sha256sums-sha256", default=DEFAULT_SUMS_SHA256)
    args = parser.parse_args(argv)
    try:
        result = verify(args.bundle, expected_sums_sha256=args.sha256sums_sha256, git_root=args.git_root)
    except VerifyError as exc:
        result = {"status": "failed", "code": exc.code}
    print(json.dumps(result, sort_keys=True, ensure_ascii=True))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
