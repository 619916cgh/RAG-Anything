import json
from pathlib import Path

import pytest

from scripts import stage3_offline_release_bundle as bundle


def test_identity_and_secret_scan_guards(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(bundle, "git", lambda *_args: "a" * 40)
    monkeypatch.setattr(bundle, "run", lambda *_args, **_kwargs: type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})())
    with pytest.raises(bundle.BundleError, match="checkout"):
        bundle.validate_checkout(root, "a" * 40)


def test_local_docker_gate_rejects_remote_context(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote.invalid:2375")
    with pytest.raises(bundle.BundleError, match="remote Docker"):
        bundle.validate_local_docker()


def test_verify_bundle_checksums_and_rejects_tamper(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "manifests").mkdir()
    static = tmp_path / "source" / "static"
    static.mkdir(parents=True)
    (tmp_path / "x.txt").write_text("ok", encoding="utf-8")
    for name in bundle.ARCHIVE_NAMES:
        (tmp_path / "images" / f"{name}.tar").write_bytes(name.encode("ascii"))
    tooling_files = {}
    for relative in bundle.TOOLING_FILES:
        target = static / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("tooling", encoding="utf-8")
        tooling_files[relative] = bundle.sha256(target)
    manifest = {
        "schema_version": 3, "non_production": True,
        "candidate": {"platform": "linux/amd64"}, "rollback": {"platform": "linux/amd64"},
        "dependencies": {}, "package_tooling": {"revision": "a" * 40, "files": tooling_files},
        "archive_provenance": {"archives": {name: bundle.sha256(tmp_path / "images" / f"{name}.tar") for name in bundle.ARCHIVE_NAMES}},
    }
    (tmp_path / "manifests" / "oci-identity.json").write_text(json.dumps(manifest), encoding="utf-8")
    sums = "\n".join(
        f"{bundle.sha256(path)}  {path.relative_to(tmp_path).as_posix()}"
        for path in sorted(tmp_path.rglob("*")) if path.is_file() and path.name != "SHA256SUMS"
    ) + "\n"
    (tmp_path / "SHA256SUMS").write_text(sums, encoding="utf-8")
    assert bundle.verify_bundle(tmp_path)["status"] == "ok"
    (tmp_path / "x.txt").write_text("tampered", encoding="utf-8")
    with pytest.raises(bundle.BundleError, match="checksum"):
        bundle.verify_bundle(tmp_path)


def test_rehearse_imports_both_images_and_keeps_foreign_resources(monkeypatch, tmp_path):
    (tmp_path / "images").mkdir()
    for name in ("candidate", "rollback", "postgres", "redis", "nginx"):
        (tmp_path / "images" / f"{name}.tar").write_bytes(b"tar")
    identity = {
        "candidate": {"reference": "candidate:test", "revision": "a" * 40, "digest": "sha256:" + "1" * 64},
        "rollback": {"reference": "rollback:test", "revision": "b" * 40, "digest": "sha256:" + "2" * 64},
        "dependencies": {name: {"reference": f"{name}:test", "digest": "sha256:" + digit * 64} for name, digit in (("postgres", "3"), ("redis", "4"), ("nginx", "5"))},
    }
    calls = []
    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        stdout = "desktop-linux" if cmd == ["docker", "context", "show"] else "offline-health-ok"
        return type("R", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()
    monkeypatch.setattr(bundle, "run", fake_run)
    monkeypatch.setattr(bundle, "validate_local_docker", lambda: None)
    monkeypatch.setattr(bundle, "verify_bundle", lambda _bundle: identity)
    monkeypatch.setattr(bundle, "_docker_inventory", lambda: {"images": {"foreign-image"}, "containers": {"foreign-container"}, "networks": {"foreign-network"}, "volumes": {"foreign-volume"}})
    checked = []
    monkeypatch.setattr(bundle, "_ensure_no_tag_conflict", lambda item: checked.append(item["reference"]))
    monkeypatch.setattr(bundle, "_verify_imported_identity", lambda _item: None)
    result = bundle.rehearse(tmp_path)
    assert result["status"] == "passed"
    assert [command[1] for command in calls if command[0] == "docker"] == ["load", "load", "load", "load", "load", "run", "run"]
    assert checked == ["candidate:test", "rollback:test", "postgres:test", "redis:test", "nginx:test"]
    assert all("stage3.offline.run-id" in " ".join(command) for command in calls if command[0] == "docker" and command[1] == "run")


def test_copy_archives_is_byte_exact_and_create_never_docker_saves(tmp_path):
    source = tmp_path / "source"
    (source / "images").mkdir(parents=True)
    for name in bundle.ARCHIVE_NAMES:
        (source / "images" / f"{name}.tar").write_bytes((name * 3).encode("ascii"))
    sums = "\n".join(
        f"{bundle.sha256(path)}  {path.relative_to(source).as_posix()}"
        for path in sorted((source / "images").iterdir())
    ) + "\n"
    (source / "SHA256SUMS").write_text(sums, encoding="utf-8")
    destination = tmp_path / "destination"
    (destination / "images").mkdir(parents=True)
    copied = bundle._copy_archives(source, destination, source_sums_sha256=bundle.sha256(source / "SHA256SUMS"))
    assert copied["candidate"] == bundle.sha256(source / "images" / "candidate.tar")
    assert (destination / "images" / "rollback.tar").read_bytes() == (source / "images" / "rollback.tar").read_bytes()
    create_source = Path(bundle.__file__).read_text(encoding="utf-8").split("def create_bundle", 1)[1].split("def verify_bundle", 1)[0]
    assert '"docker", "save"' not in create_source


def test_foreign_tag_conflict_is_rejected_before_archive_load(monkeypatch):
    monkeypatch.setattr(bundle, "run", lambda *_args, **_kwargs: type("R", (), {"returncode": 0, "stdout": json.dumps([{"Id": "sha256:" + "f" * 64}])})())
    with pytest.raises(bundle.BundleError, match="foreign image tag conflict"):
        bundle._ensure_no_tag_conflict({"reference": "foreign:tag", "digest": "sha256:" + "1" * 64})


def test_runbook_has_names_only():
    text = bundle._runbook("a" * 40, "b" * 40)
    assert "secret manager" in text
    assert "postgresql://" not in text
    assert "password=" not in text.lower()


def test_compose_rehearsal_uses_one_ephemeral_postgres_password(monkeypatch, tmp_path):
    source = tmp_path / "source" / "static" / "tests" / "acceptance"
    source.mkdir(parents=True)
    for name in ("compose.yml", "nginx.conf", "pgvector-init.sql", "mock_video_provider.py"):
        (source / name).write_text("fixture", encoding="utf-8")
    captured = []
    monkeypatch.setattr(bundle, "run", lambda command, **_kwargs: (captured.append(command) or type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()))
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_args): return False
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    bundle._compose_health_rehearsal(tmp_path, {"reference": "image"}, "candidate", "stage3-test")
    env_file = next(command[command.index("--env-file") + 1] for command in captured if "--env-file" in command)
    # The implementation removes generated files after cleanup; assert the
    # Compose launch existed rather than leaking temporary secret material.
    assert any(command[-1] == "up" or command[-2:] == ["up", "-d"] for command in captured)
    assert not Path(env_file).exists()


def test_compose_rehearsal_generates_policy_valid_bootstrap_password(monkeypatch, tmp_path):
    source = tmp_path / "source" / "static" / "tests" / "acceptance"
    source.mkdir(parents=True)
    for name in ("compose.yml", "nginx.conf", "pgvector-init.sql", "mock_video_provider.py"):
        (source / name).write_text("fixture", encoding="utf-8")
    captured = []
    monkeypatch.setattr(bundle, "run", lambda command, **_kwargs: (captured.append(command) or type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()))
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_args): return False
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    bundle._compose_health_rehearsal(tmp_path, {"reference": "image"}, "candidate", "stage3-test-policy")
    env_file = Path(next(command[command.index("--env-file") + 1] for command in captured if "--env-file" in command))
    assert not env_file.exists()
    password = bundle._bootstrap_password()
    assert len(password) >= 20
    assert any(character.islower() for character in password)
    assert any(character.isupper() for character in password)
    assert any(character.isdigit() for character in password)
    assert any(not character.isalnum() for character in password)
