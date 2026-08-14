"""Fail-fast acceptance checks for a built CPU parser runtime image."""

from __future__ import annotations

import argparse
import importlib.metadata
import shutil
import sys


FORBIDDEN_DISTRIBUTION_PREFIXES = ("nvidia-", "cuda-", "triton")


def _installed_names() -> list[str]:
    return sorted(
        {
            distribution.metadata["Name"].lower()
            for distribution in importlib.metadata.distributions()
            if distribution.metadata.get("Name")
        }
    )


def _require_command(command: str) -> None:
    if not shutil.which(command):
        raise RuntimeError(f"required executable is unavailable: {command}")


def _verify_torch(required: bool) -> None:
    try:
        import torch
    except ImportError:
        if required:
            raise RuntimeError("CPU Torch is required but unavailable") from None
        return
    if torch.version.cuda is not None:
        raise RuntimeError(f"CUDA Torch is prohibited, found: {torch.version.cuda}")


def verify(runtime: str) -> None:
    forbidden = [
        name
        for name in _installed_names()
        if name.startswith(FORBIDDEN_DISTRIBUTION_PREFIXES)
    ]
    if forbidden:
        raise RuntimeError(f"GPU runtime distributions are prohibited: {', '.join(forbidden)}")

    _verify_torch(required=runtime == "app")
    for command in ("ffmpeg", "libreoffice"):
        _require_command(command)

    if runtime == "app":
        _require_command("java")
        from docling.document_converter import DocumentConverter
        import mineru  # noqa: F401
        import paddleocr  # noqa: F401

        if DocumentConverter is None:
            raise RuntimeError("Docling DocumentConverter import failed")
        if importlib.metadata.version("opendataloader-pdf") != "2.5.0":
            raise RuntimeError("unexpected opendataloader-pdf version")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", choices=("app", "marker"), required=True)
    args = parser.parse_args()
    try:
        verify(args.runtime)
    except Exception as exc:  # pragma: no cover - exercised in container acceptance.
        print(f"CPU runtime verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"CPU runtime verification passed: {args.runtime}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
