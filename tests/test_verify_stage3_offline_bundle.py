import json
import tarfile
from pathlib import Path

import pytest

from scripts import verify_stage3_offline_bundle as verifier


def test_safe_member_rejects_escape(tmp_path):
    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as tar:
        info = tarfile.TarInfo("../../escape")
        info.size = 0
        tar.addfile(info)
    with tarfile.open(archive) as tar:
        assert not verifier._safe_member(tar.getmembers()[0])


def test_checksum_manifest_rejects_unlisted_file(tmp_path):
    (tmp_path / "ok.txt").write_text("ok", encoding="utf-8")
    (tmp_path / "extra.txt").write_text("extra", encoding="utf-8")
    (tmp_path / "SHA256SUMS").write_text(f"{verifier.checksum(tmp_path / 'ok.txt')}  ok.txt\n", encoding="utf-8")
    try:
        verifier._checksums(tmp_path, tmp_path / "SHA256SUMS")
        assert False, "expected allowlist error"
    except verifier.VerifyError as exc:
        assert exc.code == "E_ALLOWLIST"


def test_secret_references_are_names_only(tmp_path):
    assert verifier.VARNAME.fullmatch("JWT_SECRET")
    assert not verifier.VARNAME.fullmatch("JWT_SECRET=value")


def test_tooling_manifest_requires_all_fixed_tools_and_matching_hashes(tmp_path):
    static = tmp_path / "source" / "static"
    files = {}
    for relative in verifier.TOOLING_FILES:
        target = static / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixed", encoding="utf-8")
        files[relative] = verifier.checksum(target)
    identity = {"package_tooling": {"revision": "a" * 40, "files": files}}
    verifier._verify_tooling(tmp_path, identity)
    files["scripts/stage3_offline_preflight.py"] = "0" * 64
    with pytest.raises(verifier.VerifyError, match="E_TOOLING"):
        verifier._verify_tooling(tmp_path, identity)


def test_archive_provenance_rejects_mismatched_copy(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    records = {}
    for name in verifier.REQUIRED_ARCHIVES:
        archive = images / f"{name}.tar"
        archive.write_bytes(name.encode("ascii"))
        records[name] = verifier.checksum(archive)
    identity = {"archive_provenance": {"source_sha256sums": "a" * 64, "archives": records}}
    verifier._verify_archive_provenance(tmp_path, identity)
    (images / "candidate.tar").write_bytes(b"changed")
    with pytest.raises(verifier.VerifyError, match="E_ARCHIVE_PROVENANCE"):
        verifier._verify_archive_provenance(tmp_path, identity)


def _supply_chain_fixture(tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "manifests").mkdir(parents=True)
    (bundle / "evidence" / "supply-chain").mkdir(parents=True)
    archive_hashes = {name: "a" * 64 for name in verifier.REQUIRED_ARCHIVES}
    identity = {
        "archive_provenance": {"archives": archive_hashes},
        "candidate": {"digest": "sha256:" + "1" * 64, "platform": "linux/amd64", "revision": "1" * 40},
        "rollback": {"digest": "sha256:" + "2" * 64, "platform": "linux/amd64", "revision": "2" * 40},
    }
    artifacts = {}
    for name, digest in (("candidate", identity["candidate"]["digest"]), ("rollback", identity["rollback"]["digest"])):
        artifacts[name] = {}
        for kind, (artifact, output_format) in verifier.SUPPLY_CHAIN_FILES.items():
            relative = f"evidence/supply-chain/{name}-{kind}.json"
            data = {
                "archive_sha256": archive_hashes[name],
                "artifact": artifact,
                "completion_status": "unavailable",
                "database_checked_at": "2026-08-26T00:00:00Z",
                "database_status": "scanner_database_unavailable",
                "database_updated_at": "unavailable",
                "database_version": "unavailable",
                "generated_at": "2026-08-26T00:00:00Z",
                "image_digest": digest,
                "output_format": output_format,
                "platform": "linux/amd64",
                "scanner": "docker-scout",
                "scanner_version": "v1.23.1",
                "status": "unavailable",
            }
            target = bundle / relative
            target.write_text(json.dumps(data), encoding="utf-8")
            artifacts[name][kind] = {"path": relative, "sha256": verifier.checksum(target)}
    supply = {
        "archive_checksums": archive_hashes,
        "artifacts": artifacts,
        "qualification": "not-qualified",
        "v2_root_sha256": verifier.V2_REQUALIFIED_SUMS_SHA256,
    }
    (bundle / "manifests" / "supply-chain.json").write_text(json.dumps(supply), encoding="utf-8")
    return bundle, identity


def _qualified_supply_chain_fixture(tmp_path):
    bundle, identity = _supply_chain_fixture(tmp_path)
    database = {
        "checksum": "d" * 64,
        "schema_version": "v6.1.9",
        "source_verification": "official_anchore_database_checksum_verified",
        "status": "current",
        "updated_at": "2026-08-25T00:19:07Z",
        "valid": True,
    }
    supply_path = bundle / "manifests" / "supply-chain.json"
    supply = json.loads(supply_path.read_text(encoding="utf-8"))
    supply["qualification"] = "offline-release-qualified"
    supply["vulnerability_database"] = database
    for image_name in ("candidate", "rollback"):
        for kind in verifier.SUPPLY_CHAIN_FILES:
            record = supply["artifacts"][image_name][kind]
            target = bundle / record["path"]
            data = json.loads(target.read_text(encoding="utf-8"))
            scanner_name, scanner_version = verifier.SUPPLY_CHAIN_SCANNERS[kind]
            payload_name = {
                "sbom": "sbom",
                "licenses": "license_inventory",
                "vulnerabilities": "vulnerabilities",
            }[kind]
            data.update(
                {
                    "completion_status": "complete",
                    "database": database,
                    "image_revision": identity[image_name]["revision"],
                    "raw_output_sha256": "e" * 64,
                    "scanner": {
                        "asset_sha256": "f" * 64,
                        "checksums_sha256": "a" * 64,
                        "name": scanner_name,
                        "platform": "windows/amd64",
                        "source_verification": "official_release_checksum_verified",
                        "version": scanner_version,
                    },
                    "status": "passed",
                }
            )
            data[payload_name] = {}
            target.write_text(json.dumps(data), encoding="utf-8")
            record["sha256"] = verifier.checksum(target)
    supply_path.write_text(json.dumps(supply), encoding="utf-8")
    return bundle, identity


def test_supply_chain_evidence_is_semantically_bound(tmp_path):
    bundle, identity = _supply_chain_fixture(tmp_path)
    verifier._verify_supply_chain(bundle, identity)
    candidate = bundle / "evidence" / "supply-chain" / "candidate-sbom.json"
    data = json.loads(candidate.read_text(encoding="utf-8"))
    data["image_digest"] = "sha256:" + "9" * 64
    candidate.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(verifier.VerifyError, match="E_SUPPLY_CHAIN_ARTIFACT"):
        verifier._verify_supply_chain(bundle, identity)


def test_supply_chain_evidence_rejects_absolute_artifact_path(tmp_path):
    bundle, identity = _supply_chain_fixture(tmp_path)
    supply_path = bundle / "manifests" / "supply-chain.json"
    supply = json.loads(supply_path.read_text(encoding="utf-8"))
    supply["artifacts"]["candidate"]["sbom"]["path"] = "C:/outside.json"
    supply_path.write_text(json.dumps(supply), encoding="utf-8")
    with pytest.raises(verifier.VerifyError, match="E_SUPPLY_CHAIN_ARTIFACT"):
        verifier._verify_supply_chain(bundle, identity)


def test_qualified_supply_chain_binds_scanner_versions_and_checksums(tmp_path):
    bundle, identity = _qualified_supply_chain_fixture(tmp_path)
    verifier._verify_supply_chain(bundle, identity)
    target = bundle / "evidence" / "supply-chain" / "candidate-sbom.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    data["scanner"]["version"] = "0.0.0"
    target.write_text(json.dumps(data), encoding="utf-8")
    supply_path = bundle / "manifests" / "supply-chain.json"
    supply = json.loads(supply_path.read_text(encoding="utf-8"))
    supply["artifacts"]["candidate"]["sbom"]["sha256"] = verifier.checksum(target)
    supply_path.write_text(json.dumps(supply), encoding="utf-8")
    with pytest.raises(verifier.VerifyError, match="E_SUPPLY_CHAIN_EVIDENCE"):
        verifier._verify_supply_chain(bundle, identity)


def test_qualified_supply_chain_binds_manifest_database(tmp_path):
    bundle, identity = _qualified_supply_chain_fixture(tmp_path)
    target = bundle / "evidence" / "supply-chain" / "rollback-vulnerabilities.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    data["database"]["checksum"] = "0" * 64
    target.write_text(json.dumps(data), encoding="utf-8")
    supply_path = bundle / "manifests" / "supply-chain.json"
    supply = json.loads(supply_path.read_text(encoding="utf-8"))
    supply["artifacts"]["rollback"]["vulnerabilities"]["sha256"] = verifier.checksum(target)
    supply_path.write_text(json.dumps(supply), encoding="utf-8")
    with pytest.raises(verifier.VerifyError, match="E_SUPPLY_CHAIN_EVIDENCE"):
        verifier._verify_supply_chain(bundle, identity)
