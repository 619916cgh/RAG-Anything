from __future__ import annotations

from pathlib import Path
import json
import re


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "deploy" / "fast-release" / "policy.json"
LOCAL_RELEASE = ROOT / "deploy.ps1"
REMOTE_RELEASE = ROOT / "deploy" / "fast-release" / "remote-release.sh"
APP_DOCKERFILE = ROOT / "deploy" / "fast-release" / "Dockerfile.app"
NGINX_DOCKERFILE = ROOT / "deploy" / "fast-release" / "Dockerfile.nginx"


def test_policy_rejects_base_migration_and_release_tool_changes() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    patterns = [re.compile(pattern) for pattern in policy["disallowedCandidatePatterns"]]

    for path in (
        "Dockerfile",
        "frontend/package-lock.json",
        "migrations/034_example.sql",
        "migration_manifest.json",
        "docker-compose.yml",
        "deploy/fast-release/remote-release.sh",
        "deploy.ps1",
    ):
        assert any(pattern.search(path) for pattern in patterns), path


def test_policy_forbids_sensitive_or_persistent_payload_paths() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    patterns = [re.compile(pattern) for pattern in policy["forbiddenPayloadPatterns"]]

    for path in (
        ".env",
        ".env.local",
        "uploads/example.pdf",
        "rag_storage/default",
        "output/report.json",
        "models/huggingface/cache",
        "frontend/node_modules/vite",
        ".git/config",
    ):
        assert any(pattern.search(path) for pattern in patterns), path
    assert not any(pattern.search(".env.example") for pattern in patterns)


def test_thin_release_images_copy_only_staged_payload() -> None:
    app = APP_DOCKERFILE.read_text(encoding="utf-8")
    nginx = NGINX_DOCKERFILE.read_text(encoding="utf-8")

    assert "FROM ${RUNTIME_IMAGE}" in app
    assert "COPY payload/ /app/" in app
    assert "FROM ${NGINX_RUNTIME_IMAGE}" in nginx
    assert "COPY payload/frontend/dist/ /usr/share/nginx/html/" in nginx
    assert "RUN apt-get" not in app + nginx
    assert "pip install" not in app + nginx


def test_remote_release_only_switches_app_then_nginx_and_rolls_back() -> None:
    content = REMOTE_RELEASE.read_text(encoding="utf-8")

    assert 'allowedComposeServices' not in content
    assert "up -d --no-deps --no-build --force-recreate app" in content
    assert "up -d --no-deps --no-build --force-recreate nginx" in content
    assert content.index("force-recreate app") < content.index("force-recreate nginx")
    assert "trap rollback ERR INT TERM" in content
    assert "rollback_app_image" in content
    assert "rollback_nginx_image" in content
    assert "assert_direct_health" in content
    assert "assert_full_health" in content
    assert 'minimum_free_gb="${10}"' in content
    assert 'input_manifest="${13}"' in content
    assert "Release manifest commit does not match" in content
    assert "Release manifest checksum does not match" in content
    assert '\\"commit_sha\\"[[:space:]]*:[[:space:]]*' in content
    assert "migrate" not in content.lower().replace("does not invoke migration", "")
    assert "prune" not in content.lower()


def test_local_release_requires_commit_and_ssh_key() -> None:
    content = LOCAL_RELEASE.read_text(encoding="utf-8")

    assert "ValidatePattern('^[0-9a-fA-F]{40}$')" in content
    assert "git archive" in content
    assert "--format=zip" in content
    assert "Expand-Archive" in content
    assert "[Text.UTF8Encoding]::new($false)" in content
    assert "Password-based fast release is intentionally unsupported" in content
    assert "BatchMode=yes" in content
    assert "deploy\\fast-release\\manifests" in content
    assert "Split-Path -Parent $MyInvocation.MyCommand.Definition" in content
