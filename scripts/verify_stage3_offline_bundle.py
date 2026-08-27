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
VALUE_SECRET = re.compile(r"(?:postgres(?:ql)?://|redis://|https?://[^\s]+:[^\s@]+@|(?:sk|ghp)_[A-Za-z0-9_-]{12,})", re.I)
DEFAULT_SUMS_SHA256 = "b7576624c7ed2cb1eddcc151b4681501ee726dc48929ea75f5e8b99309150d41"
V2_REQUALIFIED_SUMS_SHA256 = "e853de298fd8b487d3eea793943fc6f8dcc87e7a5333d8ea61f65cc1e69ff1ae"
REQUIRED_ARCHIVES = {"candidate", "rollback", "postgres", "redis", "nginx"}
SUPPLY_CHAIN_ARTIFACTS = {"sbom", "licenses", "vulnerabilities"}
SUPPLY_CHAIN_FILES = {
    "sbom": ("sbom", "spdx-json"),
    "licenses": ("license-inventory", "json"),
    "vulnerabilities": ("vulnerability-snapshot", "grype-json"),
}
SUPPLY_CHAIN_SCANNERS = {
    "sbom": ("syft", "1.51.0"),
    "licenses": ("syft", "1.51.0"),
    "vulnerabilities": ("grype", "0.117.0"),
}
TOOLING_FILES = {
    "scripts/stage3_offline_release_bundle.py",
    "scripts/verify_stage3_offline_bundle.py",
    "scripts/stage3_offline_preflight.py",
    "scripts/stage3_offline_release_dry_run.py",
}


class VerifyError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _verify_supply_chain(bundle: Path, identity: dict[str, Any]) -> None:
    manifest_path = bundle / "manifests" / "supply-chain.json"
    try:
        supply = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerifyError("E_SUPPLY_CHAIN_MANIFEST") from exc
    if not isinstance(supply, dict) or supply.get("qualification") not in {"not-qualified", "offline-release-qualified"}:
        raise VerifyError("E_SUPPLY_CHAIN_STATUS")
    if supply.get("v2_root_sha256") != V2_REQUALIFIED_SUMS_SHA256:
        raise VerifyError("E_SUPPLY_CHAIN_PROVENANCE")
    archive_provenance = identity.get("archive_provenance", {})
    archives = archive_provenance.get("archives") if isinstance(archive_provenance, dict) else None
    if supply.get("archive_checksums") != archives:
        raise VerifyError("E_SUPPLY_CHAIN_ARCHIVE")
    qualified = supply.get("qualification") == "offline-release-qualified"
    database = supply.get("vulnerability_database")
    if qualified and (not isinstance(database, dict) or database.get("status") != "current" or database.get("valid") is not True or not SHA.fullmatch(str(database.get("checksum", ""))) or not database.get("updated_at")):
        raise VerifyError("E_SUPPLY_CHAIN_DATABASE")
    artifacts = supply.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"candidate", "rollback"}:
        raise VerifyError("E_SUPPLY_CHAIN_ARTIFACT")
    for image_name in ("candidate", "rollback"):
        image = identity.get(image_name, {})
        records = artifacts.get(image_name)
        if not isinstance(records, dict) or set(records) != SUPPLY_CHAIN_ARTIFACTS:
            raise VerifyError("E_SUPPLY_CHAIN_ARTIFACT")
        archive_sha = archives.get(image_name) if isinstance(archives, dict) else None
        for kind, (artifact_name, output_format) in SUPPLY_CHAIN_FILES.items():
            record = records.get(kind)
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                raise VerifyError("E_SUPPLY_CHAIN_ARTIFACT")
            relative_path = Path(record["path"])
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise VerifyError("E_SUPPLY_CHAIN_ARTIFACT")
            target = bundle / relative_path
            if target.is_symlink() or not target.is_file() or not SHA.fullmatch(str(record.get("sha256", ""))) or checksum(target) != record["sha256"]:
                raise VerifyError("E_SUPPLY_CHAIN_ARTIFACT")
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise VerifyError("E_SUPPLY_CHAIN_EVIDENCE") from exc
            if qualified:
                scanner = data.get("scanner") if isinstance(data, dict) else None
                expected_scanner, expected_version = SUPPLY_CHAIN_SCANNERS[kind]
                required_payload = {"sbom": "sbom", "licenses": "license_inventory", "vulnerabilities": "vulnerabilities"}[kind]
                if (not isinstance(data, dict) or data.get("artifact") != artifact_name or data.get("image_digest") != image.get("digest")
                        or data.get("image_revision") != image.get("revision") or data.get("platform") != "linux/amd64"
                        or data.get("archive_sha256") != archive_sha or data.get("output_format") != output_format
                        or data.get("completion_status") != "complete" or data.get("status") != "passed"
                        or not isinstance(scanner, dict) or scanner.get("name") != expected_scanner
                        or scanner.get("version") != expected_version
                        or scanner.get("platform") != "windows/amd64" or scanner.get("source_verification") != "official_release_checksum_verified"
                        or not SHA.fullmatch(str(scanner.get("asset_sha256", ""))) or not SHA.fullmatch(str(scanner.get("checksums_sha256", "")))
                        or not SHA.fullmatch(str(data.get("raw_output_sha256", "")))
                        or data.get("database") != database or required_payload not in data):
                    raise VerifyError("E_SUPPLY_CHAIN_EVIDENCE")
                encoded = json.dumps(data, ensure_ascii=True).lower()
                if VALUE_SECRET.search(encoded) or any(token in encoded for token in ("http://", "https://", "\\\\", "c:/", "/users/", "authorization")):
                    raise VerifyError("E_SUPPLY_CHAIN_REDACTION")
                continue
            if (not isinstance(data, dict) or data.get("artifact") != artifact_name
                    or data.get("image_digest") != image.get("digest")
                    or data.get("platform") != image.get("platform")
                    or data.get("platform") != "linux/amd64"
                    or data.get("archive_sha256") != archive_sha
                    or data.get("scanner") != "docker-scout"
                    or not data.get("scanner_version")
                    or data.get("output_format") != output_format
                    or data.get("completion_status") != "unavailable"
                    or data.get("status") != "unavailable"
                    or data.get("database_status") != "scanner_database_unavailable"
                    or not data.get("generated_at") or not data.get("database_checked_at")
                    or not data.get("database_version") or not data.get("database_updated_at")
                    or VALUE_SECRET.search(json.dumps(data, ensure_ascii=True))):
                raise VerifyError("E_SUPPLY_CHAIN_EVIDENCE")
            if any(token in json.dumps(data, ensure_ascii=True).lower() for token in ("authorization", "postgresql://", "redis://", "\\\\", "c:/", "/users/")):
                raise VerifyError("E_SUPPLY_CHAIN_REDACTION")


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


def _verify_source(bundle: Path, identity: dict[str, Any]) -> None:
    source = identity.get("source", {})
    candidate = identity.get("candidate", {})
    if not isinstance(source, dict) or source.get("revision") != candidate.get("revision"):
        raise VerifyError("E_SOURCE")
    relative = source.get("path")
    if not isinstance(relative, str):
        raise VerifyError("E_SOURCE")
    target = bundle / "source" / relative
    if target.is_symlink() or not target.is_file() or checksum(target) != source.get("sha256"):
        raise VerifyError("E_SOURCE")
    try:
        with tarfile.open(target, "r") as archive:
            if not archive.getmembers() or any(not _safe_member(member) for member in archive.getmembers()):
                raise VerifyError("E_SOURCE")
    except (tarfile.TarError, OSError) as exc:
        raise VerifyError("E_SOURCE") from exc


def _verify_tooling(bundle: Path, identity: dict[str, Any]) -> None:
    tooling = identity.get("package_tooling", {})
    files = tooling.get("files") if isinstance(tooling, dict) else None
    if not GIT_SHA.fullmatch(str(tooling.get("revision", ""))) or not isinstance(files, dict) or set(files) != TOOLING_FILES:
        raise VerifyError("E_TOOLING")
    for relative in TOOLING_FILES:
        target = bundle / "source" / "static" / relative
        if not SHA.fullmatch(str(files.get(relative, ""))) or target.is_symlink() or not target.is_file() or checksum(target) != files[relative]:
            raise VerifyError("E_TOOLING")


def _verify_archive_provenance(bundle: Path, identity: dict[str, Any]) -> None:
    provenance = identity.get("archive_provenance", {})
    archives = provenance.get("archives") if isinstance(provenance, dict) else None
    if not SHA.fullmatch(str(provenance.get("source_sha256sums", ""))) or not isinstance(archives, dict) or set(archives) != REQUIRED_ARCHIVES:
        raise VerifyError("E_ARCHIVE_PROVENANCE")
    for name in REQUIRED_ARCHIVES:
        archive = bundle / "images" / f"{name}.tar"
        if not SHA.fullmatch(str(archives.get(name, ""))) or not archive.is_file() or checksum(archive) != archives[name]:
            raise VerifyError("E_ARCHIVE_PROVENANCE")


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
    legacy_bundle = checksum(sums) == DEFAULT_SUMS_SHA256 and identity.get("schema_version") == 2
    if (identity.get("schema_version") not in ({2, 3} if legacy_bundle else {3})
            or not identity.get("non_production") or not all(isinstance(x, dict) for x in (candidate, rollback))):
        raise VerifyError("E_IDENTITY")
    if not GIT_SHA.fullmatch(str(candidate.get("revision", ""))) or not GIT_SHA.fullmatch(str(rollback.get("revision", ""))):
        raise VerifyError("E_GIT_SHA")
    if identity.get("ancestry", {}).get("rollback_is_candidate_ancestor") is not True:
        raise VerifyError("E_GIT_ANCESTRY")
    _verify_git(git_root, candidate["revision"], rollback["revision"])
    if not legacy_bundle:
        _verify_source(bundle, identity)
        _verify_tooling(bundle, identity)
        _verify_archive_provenance(bundle, identity)
        _verify_supply_chain(bundle, identity)
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
