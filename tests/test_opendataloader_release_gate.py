import json
import subprocess
import sys
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "opendataloader_release_gate.py"
REVISION = "a" * 40


def _wheel(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("opendataloader_pdf/LICENSE", "Apache-2.0")
        archive.writestr("opendataloader_pdf/NOTICE", "notice")
        archive.writestr("opendataloader_pdf/THIRD_PARTY/THIRD_PARTY_LICENSES.md", "licenses")
        archive.writestr("opendataloader_pdf/THIRD_PARTY/THIRD_PARTY_NOTICES.md", "third party")
        archive.writestr("opendataloader_pdf/THIRD_PARTY/licenses/MIT.txt", "MIT")
        archive.writestr("opendataloader_pdf/jar/opendataloader-pdf-cli.jar", b"jar")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_collects_wheel_hash_jar_and_notice_inventory(tmp_path: Path):
    wheel = tmp_path / "opendataloader_pdf-2.5.0-py3-none-any.whl"
    manifest = tmp_path / "manifest.json"
    notice_root = tmp_path / "OSS_NOTICES" / "opendataloader-pdf"
    _wheel(wheel)

    result = _run(
        "collect",
        "--wheel",
        str(wheel),
        "--notice-root",
        str(notice_root),
        "--manifest",
        str(manifest),
        "--source-revision",
        REVISION,
        "--source-url",
        f"https://github.com/opendataloader-project/opendataloader-pdf/commit/{REVISION}",
    )

    assert result.returncode == 0, result.stderr
    value = json.loads(manifest.read_text(encoding="utf-8"))
    assert value["wheel"]["sha256"]
    assert value["bundled_jars"][0]["path"].endswith(".jar")
    assert (notice_root / "THIRD_PARTY" / "THIRD_PARTY_NOTICES.md").is_file()


def test_collect_rejects_non_upstream_immutable_url(tmp_path: Path):
    wheel = tmp_path / "odl.whl"
    _wheel(wheel)

    result = _run(
        "collect",
        "--wheel",
        str(wheel),
        "--notice-root",
        str(tmp_path / "notices"),
        "--manifest",
        str(tmp_path / "manifest.json"),
        "--source-revision",
        REVISION,
        "--source-url",
        f"https://example.invalid/commit/{REVISION}",
    )

    assert result.returncode == 2
    assert "upstream immutable" in result.stderr


def test_collect_rejects_non_immutable_source_revision(tmp_path: Path):
    wheel = tmp_path / "odl.whl"
    _wheel(wheel)

    result = _run(
        "collect",
        "--wheel",
        str(wheel),
        "--notice-root",
        str(tmp_path / "notices"),
        "--manifest",
        str(tmp_path / "manifest.json"),
        "--source-revision",
        "v2.5.0",
        "--source-url",
        "https://example.invalid/source",
    )

    assert result.returncode == 2
    assert "immutable" in result.stderr


def test_verify_fails_closed_without_legal_evidence(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "integration": "opendataloader-pdf",
                "version": "2.5.0",
                "source_revision": REVISION,
                "corresponding_source_urls": ["https://example.invalid/source"],
                "wheel": {"sha256": "b" * 64},
                "bundled_jars": [{"path": "jar/odl.jar", "sha256": "c" * 64}],
                "notices": [{"path": "LICENSE", "sha256": "d" * 64}],
            }
        ),
        encoding="utf-8",
    )
    sbom = tmp_path / "sbom.json"
    sbom.write_text(
        json.dumps({"components": [{"name": "component", "version": "1.0", "licenses": [{"license": {"id": "MIT"}}]}]}),
        encoding="utf-8",
    )

    result = _run(
        "verify",
        "--manifest",
        str(manifest),
        "--notice-root",
        str(tmp_path / "missing-notices"),
        "--sbom",
        str(sbom),
        "--reconciliation",
        str(tmp_path / "missing-reconciliation.json"),
        "--approval",
        str(tmp_path / "missing-approval.json"),
        "--image-digest",
        "sha256:" + "e" * 64,
    )

    assert result.returncode == 2
    assert "failed" in result.stderr
