import hashlib
from pathlib import Path

import pytest

from scripts import stage3_supply_chain_requalification as subject


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(root: Path) -> Path:
    (root / "images").mkdir(parents=True)
    for name in subject.ARCHIVES:
        path = root / "images" / f"{name}.tar"
        path.write_text(name, encoding="utf-8")
    (root / "manifests").mkdir()
    (root / "manifests" / "oci-identity.json").write_text('{"candidate":{"digest":"sha256:abc","platform":"linux/amd64"},"rollback":{"digest":"sha256:def","platform":"linux/amd64"}}', encoding="utf-8")
    records = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        records.append(f"{_checksum(path)}  {path.relative_to(root).as_posix()}")
    sums = root / "SHA256SUMS"
    sums.write_text("\n".join(records) + "\n", encoding="utf-8")
    return root


def test_create_v3_copies_archives_and_records_unavailable_evidence(tmp_path, monkeypatch):
    v2 = _bundle(tmp_path / "v2")
    monkeypatch.setattr(subject, "ARCHIVES", {name: _checksum(v2 / "images" / f"{name}.tar") for name in subject.ARCHIVES})
    monkeypatch.setattr(subject, "V2_SUMS_SHA256", _checksum(v2 / "SHA256SUMS"))
    result = subject.create_v3(v2=v2, output=tmp_path / "v3", scanner_version="vX", database_status="unavailable", scanner_attempt="bounded_timeout")
    assert result["status"] == "not-qualified"
    assert result["root_sha256"] != _checksum(v2 / "SHA256SUMS")
    assert (tmp_path / "v3" / "evidence" / "supply-chain" / "candidate-sbom.json").is_file()
    for name in subject.ARCHIVES:
        assert _checksum(v2 / "images" / f"{name}.tar") == _checksum(tmp_path / "v3" / "images" / f"{name}.tar")


def test_create_v3_rejects_wrong_v2_root(tmp_path):
    v2 = _bundle(tmp_path / "v2")
    with pytest.raises(subject.RequalificationError, match="v2_root_checksum_mismatch"):
        subject.create_v3(v2=v2, output=tmp_path / "v3", scanner_version="vX", database_status="unavailable", scanner_attempt="bounded_timeout")
