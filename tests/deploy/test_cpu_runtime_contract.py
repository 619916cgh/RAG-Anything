from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
APP_LOCK = ROOT / "requirements.cpu-linux-py311-x86_64.lock"
MARKER_LOCK = ROOT / "requirements.marker.cpu-linux-py311-x86_64.lock"
PYTORCH_LOCK = ROOT / "requirements.cpu-pytorch-linux-py311-x86_64.lock"
DOCKERFILE = ROOT / "Dockerfile"
RUNTIME_CHECK = ROOT / "scripts" / "verify_cpu_runtime.py"
FORBIDDEN = re.compile(r"^(?:nvidia-|cuda-|triton(?:==|-))", re.IGNORECASE)


def _requirement_names(lock_path: Path) -> list[str]:
    return [
        line.split("==", 1)[0]
        for line in lock_path.read_text(encoding="utf-8").splitlines()
        if "==" in line and not line.startswith((" ", "#", "--"))
    ]


def test_cpu_locks_are_hash_verified_and_exclude_gpu_packages() -> None:
    for lock_path in (APP_LOCK, MARKER_LOCK, PYTORCH_LOCK):
        content = lock_path.read_text(encoding="utf-8")
        assert "--hash=sha256:" in content
        assert not [name for name in _requirement_names(lock_path) if FORBIDDEN.match(name)]


def test_app_lock_pins_cpu_torch_and_torchvision() -> None:
    content = APP_LOCK.read_text(encoding="utf-8")
    assert re.search(r"^torch==\d+\.\d+\.\d+\+cpu\b", content, re.MULTILINE)
    assert re.search(r"^torchvision==\d+\.\d+\.\d+\+cpu\b", content, re.MULTILINE)
    assert "uvicorn==0.52.1" in content
    assert "uvicorn==0.52.3" not in content


def test_dockerfile_uses_cpu_locks_before_source_overlay() -> None:
    content = DOCKERFILE.read_text(encoding="utf-8")
    app_runtime = content.index("FROM python:3.11-slim-bookworm AS app-runtime")
    app_source = content.index("FROM app-runtime AS app-source")
    app_lock = content.index("requirements.cpu-linux-py311-x86_64.lock")
    source_copy = content.index("COPY . .", app_source)

    assert app_runtime < app_lock < app_source < source_copy
    assert "requirements.cpu-pytorch-linux-py311-x86_64.lock" in content
    assert "--index-url ${PYTORCH_CPU_INDEX_URL}" in content
    assert "--no-deps" in content
    assert "--extra-index-url ${PYTORCH_CPU_INDEX_URL}" not in content
    assert "--require-hashes" in content
    assert "ARG PIP_NETWORK_TIMEOUT=600" in content
    assert "ARG PIP_NETWORK_RETRIES=12" in content
    assert "--timeout ${PIP_NETWORK_TIMEOUT} --retries ${PIP_NETWORK_RETRIES}" in content
    assert "verify_cpu_runtime.py --runtime app" in content
    assert "FROM python:3.11-slim-bookworm AS marker-runtime" in content
    assert "FROM marker-runtime AS marker" in content
    assert "requirements.marker.cpu-linux-py311-x86_64.lock" in content


def test_runtime_acceptance_script_checks_cpu_and_parser_boundaries() -> None:
    content = RUNTIME_CHECK.read_text(encoding="utf-8")
    for required in (
        "torch.version.cuda",
        "FORBIDDEN_DISTRIBUTION_PREFIXES",
        "DocumentConverter",
        "opendataloader-pdf",
        '"ffmpeg"',
        '"libreoffice"',
        '"java"',
    ):
        assert required in content
