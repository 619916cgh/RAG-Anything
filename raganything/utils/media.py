"""Shared media-type predicates used at upload and worker boundaries."""

from __future__ import annotations

import os
from pathlib import Path


SUPPORTED_VIDEO_EXTENSIONS = frozenset({".mp4", ".avi", ".mov", ".mkv", ".webm"})


def is_supported_video_file(path_or_name: str | os.PathLike[str]) -> bool:
    """Return whether a path uses an extension handled by the v2 video pipeline."""
    return Path(path_or_name).suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS

