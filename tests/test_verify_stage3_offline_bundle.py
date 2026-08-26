import json
import tarfile
from pathlib import Path

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
