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
    (tmp_path / "manifests").mkdir()
    (tmp_path / "x.txt").write_text("ok", encoding="utf-8")
    manifest = {"non_production": True, "candidate": {"platform": "linux/amd64"}, "rollback": {"platform": "linux/amd64"}}
    (tmp_path / "manifests" / "oci-identity.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "SHA256SUMS").write_text(f"{bundle.sha256(tmp_path / 'x.txt')}  x.txt\n{bundle.sha256(tmp_path / 'manifests' / 'oci-identity.json')}  manifests/oci-identity.json\n", encoding="utf-8")
    assert bundle.verify_bundle(tmp_path)["status"] == "ok"
    (tmp_path / "x.txt").write_text("tampered", encoding="utf-8")
    with pytest.raises(bundle.BundleError, match="checksum"):
        bundle.verify_bundle(tmp_path)


def test_rehearse_imports_both_images_and_keeps_foreign_resources(monkeypatch, tmp_path):
    (tmp_path / "images").mkdir()
    for name in ("candidate", "rollback", "postgres", "redis", "nginx"):
        (tmp_path / "images" / f"{name}.tar").write_bytes(b"tar")
    (tmp_path / "manifests").mkdir()
    identity = {"non_production": True, "candidate": {"platform": "linux/amd64", "revision": "a" * 40, "digest": "sha256:" + "1" * 64}, "rollback": {"platform": "linux/amd64", "revision": "b" * 40, "digest": "sha256:" + "2" * 64}}
    (tmp_path / "manifests" / "oci-identity.json").write_text(json.dumps(identity), encoding="utf-8")
    files = []
    for p in tmp_path.rglob("*"):
        if p.is_file() and p.name != "SHA256SUMS": files.append(f"{bundle.sha256(p)}  {p.relative_to(tmp_path).as_posix()}")
    (tmp_path / "SHA256SUMS").write_text("\n".join(files) + "\n", encoding="utf-8")
    calls = []
    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        stdout = "desktop-linux" if cmd == ["docker", "context", "show"] else "offline-health-ok"
        return type("R", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()
    monkeypatch.setattr(bundle, "run", fake_run)
    monkeypatch.setattr(bundle, "validate_local_docker", lambda: None)
    result = bundle.rehearse(tmp_path)
    assert result["status"] == "passed"
    assert [command[1] for command in calls if command[:2] != ["docker", "context"] and command[0] == "docker"] == ["load", "load", "load", "load", "run", "load", "run"]
    assert all("stage3.offline.run-id" in " ".join(command) for command in calls if command[0] == "docker" and command[1] == "run")


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
