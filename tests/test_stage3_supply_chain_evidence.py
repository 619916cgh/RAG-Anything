import json

from scripts import stage3_supply_chain_evidence as subject


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_qualify_writes_redacted_archive_bound_evidence(tmp_path):
    bundle = tmp_path / "bundle"
    raw_dir = tmp_path / "raw"
    archive_checksums = {}
    for image_name in ("candidate", "rollback", "postgres", "redis", "nginx"):
        target = bundle / "images" / f"{image_name}.tar"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(image_name.encode("ascii"))
        archive_checksums[image_name] = subject.checksum(target)
    identity = {
        "archive_provenance": {"archives": archive_checksums},
        "candidate": {"digest": "sha256:" + "1" * 64, "platform": "linux/amd64", "revision": "1" * 40},
        "rollback": {"digest": "sha256:" + "2" * 64, "platform": "linux/amd64", "revision": "2" * 40},
        "v3_supply_chain": {"source_v2_sha256sums": "3" * 64},
    }
    _write_json(bundle / "manifests" / "oci-identity.json", identity)
    for image_name in ("candidate", "rollback"):
        _write_json(
            raw_dir / f"{image_name}-raw.spdx.json",
            {
                "packages": [{"name": "package", "versionInfo": "1.0", "licenseDeclared": "MIT"}],
                "spdxVersion": "SPDX-2.3",
            },
        )
        _write_json(
            raw_dir / f"{image_name}-raw.grype.json",
            {"matches": [{"artifact": {"name": "package", "version": "1.0"}, "vulnerability": {"id": "CVE-2026-0001"}}]},
        )
    tools = [
        {"name": "syft", "version": "1.51.0", "platform": "windows/amd64", "checksum_verified": True, "asset_sha256": "4" * 64, "checksums_sha256": "5" * 64},
        {"name": "grype", "version": "0.117.0", "platform": "windows/amd64", "checksum_verified": True, "asset_sha256": "6" * 64, "checksums_sha256": "7" * 64},
    ]
    tool_file = tmp_path / "tools.json"
    db_file = tmp_path / "database.json"
    _write_json(tool_file, tools)
    _write_json(db_file, {"from": "https://grype.anchore.io/databases/v6/database_2026-08-25T00:19:07Z_checksum=sha256%3A" + "8" * 64, "schemaVersion": "v6.1.9", "valid": True})

    result = subject.qualify(bundle=bundle, raw_dir=raw_dir, tool_verification=tool_file, database_status=db_file)

    assert result["status"] == "offline-release-qualified"
    record = json.loads((bundle / "evidence" / "supply-chain" / "candidate-vulnerabilities.json").read_text(encoding="utf-8"))
    assert record["scanner"]["name"] == "grype"
    assert record["database"]["status"] == "current"
    assert not subject.BAD.search(json.dumps(record))
