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
