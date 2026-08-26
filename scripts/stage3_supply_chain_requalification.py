#!/usr/bin/env python3
"""Create a v3 Stage 3 bundle with archive-bound supply-chain evidence.

The command is deliberately conservative: it only copies a verified v2
bundle into a fresh directory, preserves image archives byte-for-byte, and
records an unavailable scanner as a release blocker rather than inventing an
SBOM, license inventory, or vulnerability result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


V2_SUMS_SHA256 = "e853de298fd8b487d3eea793943fc6f8dcc87e7a5333d8ea61f65cc1e69ff1ae"
ARCHIVES = {
    "candidate": "745f7a6fb7647fc33247e86abb99e6d664489893b871ad61d05c2f063208923e",
    "rollback": "8d654987609e9ec7e7a6accd11bf71b2b56589c13716ed418c20f11042fc1c88",
    "postgres": "c8ea9511b4cf5b510a737ffb4bd409412e6c3b857c73dde2979ddd410bf99d5f",
    "redis": "8bf0105c92f562367889d7fc5947321c6313edb01ee6df80683724ccce56dc1a",
    "nginx": "a962e86019ff8ed6596fb1c50ff9b06f45de87a6619d09d2f151f9a37ae3149b",
}
SENSITIVE = re.compile(r"(?:authorization|credential|database[_-]?url|dsn|password|secret|token|api[_-]?key)", re.I)
VALUE_SECRET = re.compile(r"(?:postgres(?:ql)?://|redis://|https?://[^\s]+:[^\s@]+@|(?:sk|ghp)_[A-Za-z0-9_-]{12,})", re.I)


class RequalificationError(RuntimeError):
    pass


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_sums(bundle: Path) -> set[str]:
    sums = bundle / "SHA256SUMS"
    if not sums.is_file() or checksum(sums) != V2_SUMS_SHA256:
        raise RequalificationError("v2_root_checksum_mismatch")
    listed: set[str] = set()
    for line in sums.read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise RequalificationError("v2_checksum_format_invalid") from exc
        target = bundle / relative
        if (not re.fullmatch(r"[0-9a-f]{64}", digest) or Path(relative).is_absolute()
                or ".." in Path(relative).parts or relative in listed
                or not target.is_file() or target.is_symlink() or checksum(target) != digest):
            raise RequalificationError("v2_checksum_mismatch")
        listed.add(relative)
    actual = {item.relative_to(bundle).as_posix() for item in bundle.rglob("*") if item.is_file() and item != sums}
    if listed != actual:
        raise RequalificationError("v2_allowlist_mismatch")
    return listed


def verify_v2(bundle: Path) -> dict[str, str]:
    bundle = bundle.resolve()
    _read_sums(bundle)
    actual = {}
    for name, expected in ARCHIVES.items():
        archive = bundle / "images" / f"{name}.tar"
        if not archive.is_file() or checksum(archive) != expected:
            raise RequalificationError(f"v2_archive_mismatch:{name}")
        actual[name] = expected
    return actual


def _write_json(path: Path, value: Any) -> None:
    encoded = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if SENSITIVE.search(encoded) or VALUE_SECRET.search(encoded):
        raise RequalificationError("evidence_redaction_rejected")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def _write_sums(bundle: Path) -> str:
    sums = bundle / "SHA256SUMS"
    records = []
    for item in sorted((entry for entry in bundle.rglob("*") if entry.is_file() and entry != sums), key=lambda entry: entry.relative_to(bundle).as_posix()):
        if item.is_symlink():
            raise RequalificationError("bundle_symlink_rejected")
        records.append(f"{checksum(item)}  {item.relative_to(bundle).as_posix()}")
    sums.write_text("\n".join(records) + "\n", encoding="utf-8")
    return checksum(sums)


def create_v3(*, v2: Path, output: Path, scanner_version: str, database_status: str, scanner_attempt: str) -> dict[str, Any]:
    if output.exists():
        raise RequalificationError("output_already_exists")
    archive_checksums = verify_v2(v2)
    shutil.copytree(v2, output, copy_function=shutil.copy2)
    # Confirm the source did not drift while the potentially long copy ran.
    verify_v2(v2)
    copied_checksums = {name: checksum(output / "images" / f"{name}.tar") for name in ARCHIVES}
    if copied_checksums != archive_checksums:
        raise RequalificationError("v3_archive_copy_mismatch")
    identity_path = output / "manifests" / "oci-identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    artifact_inputs = {
        "candidate": identity["candidate"],
        "rollback": identity["rollback"],
    }
    evidence_root = output / "evidence" / "supply-chain"
    for name, image in artifact_inputs.items():
        base = {
            "archive_sha256": archive_checksums[name],
            "database_status": database_status,
            "generated_at": now,
            "image_digest": image["digest"],
            "platform": image["platform"],
            "scanner": "docker-scout",
            "scanner_version": scanner_version,
            "source": "v3-image-archive",
        }
        _write_json(evidence_root / f"{name}-sbom.json", {
            **base, "artifact": "sbom", "status": "unavailable",
            "reason": scanner_attempt,
        })
        _write_json(evidence_root / f"{name}-licenses.json", {
            **base, "artifact": "license-inventory", "status": "unavailable",
            "reason": "no_verifiable_sbom_available",
        })
        _write_json(evidence_root / f"{name}-vulnerabilities.json", {
            **base, "artifact": "vulnerability-snapshot", "status": "unavailable",
            "reason": "scanner_database_unavailable",
        })
    supply_chain = {
        "archive_checksums": archive_checksums,
        "created_at": now,
        "qualification": "not-qualified",
        "single_remaining_blocker": "scanner_database_and_real_sbom_unavailable",
        "v2_root_sha256": V2_SUMS_SHA256,
        "v3_archive_copy": "byte-identical",
        "vulnerability_database": {"status": database_status, "scanner": "docker-scout", "version": scanner_version},
    }
    _write_json(output / "manifests" / "supply-chain.json", supply_chain)
    identity["v3_supply_chain"] = {
        "qualification": supply_chain["qualification"],
        "source_v2_sha256sums": V2_SUMS_SHA256,
        "archives": archive_checksums,
    }
    _write_json(identity_path, identity)
    root_checksum = _write_sums(output)
    if root_checksum == V2_SUMS_SHA256:
        raise RequalificationError("v3_root_checksum_unexpectedly_matches_v2")
    return {"status": "not-qualified", "bundle": str(output.resolve()), "files": len(_read_v3_sums(output)) + 1,
            "root_sha256": root_checksum, "archive_checksums": archive_checksums}


def _read_v3_sums(bundle: Path) -> set[str]:
    sums = bundle / "SHA256SUMS"
    records: set[str] = set()
    for line in sums.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        target = bundle / relative
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or not target.is_file() or checksum(target) != digest:
            raise RequalificationError("v3_checksum_mismatch")
        records.add(relative)
    return records


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v2", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scanner-version", required=True)
    parser.add_argument("--database-status", required=True)
    parser.add_argument("--scanner-attempt", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(create_v3(v2=args.v2, output=args.output, scanner_version=args.scanner_version,
                                   database_status=args.database_status, scanner_attempt=args.scanner_attempt),
                         ensure_ascii=True, sort_keys=True))
        return 0
    except (OSError, ValueError, RequalificationError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)[:160]}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
