"""Fail-closed completion audit for newly uploaded controlled media."""

from __future__ import annotations

import os
import hashlib
import hmac
import threading
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from raganything.services.pg_state_repo import get_pg_pool
from raganything.services.provenance import CitationProvenanceError
from raganything.utils.media import is_supported_video_file


MEDIA_DELIVERY_VERSION = 2
_MEDIA_HASH_CACHE_MAX = 256
_MEDIA_HASH_CACHE: OrderedDict[tuple[str, int, int, int, str], bool] = OrderedDict()
_MEDIA_HASH_CACHE_LOCK = threading.Lock()


def _failure() -> CitationProvenanceError:
    return CitationProvenanceError("Required media delivery contract is incomplete")


def _controlled_video_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    roots = [Path.cwd() / "uploads"]
    roots.extend(
        Path(item)
        for item in os.environ.get("VIDEO_ASSET_ROOTS", "").split(os.pathsep)
        if item
    )
    try:
        candidate = Path(value)
        if not candidate.is_absolute() or candidate.is_symlink():
            return None
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file() or not is_supported_video_file(resolved):
            return None
        for root in roots:
            controlled_root = root.resolve(strict=True)
            if controlled_root.is_symlink():
                continue
            try:
                resolved.relative_to(controlled_root)
            except ValueError:
                continue
            return resolved
    except (OSError, RuntimeError, ValueError):
        return None
    return None


def media_file_sha256(path: Path) -> str:
    """Return a media digest without exposing its path to callers."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def media_file_sha256_matches(path: Path, expected_sha256: str) -> bool:
    """Verify a controlled media file while caching unchanged file identities."""
    expected = str(expected_sha256 or "").lower()
    if len(expected) != 64:
        return False
    try:
        stat = path.stat()
        key = (
            str(path.resolve()),
            int(stat.st_size),
            int(stat.st_mtime_ns),
            int(stat.st_ctime_ns),
            expected,
        )
    except OSError:
        return False

    with _MEDIA_HASH_CACHE_LOCK:
        cached = _MEDIA_HASH_CACHE.get(key)
        if cached is not None:
            _MEDIA_HASH_CACHE.move_to_end(key)
            return cached

    try:
        matches = hmac.compare_digest(media_file_sha256(path), expected)
    except OSError:
        matches = False

    if matches:
        with _MEDIA_HASH_CACHE_LOCK:
            _MEDIA_HASH_CACHE[key] = True
            _MEDIA_HASH_CACHE.move_to_end(key)
            while len(_MEDIA_HASH_CACHE) > _MEDIA_HASH_CACHE_MAX:
                _MEDIA_HASH_CACHE.popitem(last=False)
    return matches


async def audit_media_delivery_v2(
    *,
    kb_name: str,
    document_id: str,
    source_sha256: str,
    chunk_ids: Sequence[str],
    metadata: Mapping[str, Any] | None,
    require_video: bool,
    pool: Any = None,
) -> None:
    """Prove that every declared new-upload media locator is durable and owned."""
    if not kb_name or not document_id or len(source_sha256) != 64:
        raise _failure()
    declared_chunks = {str(value) for value in chunk_ids if value}
    if not declared_chunks:
        raise _failure()
    selected_pool = pool if pool is not None else get_pg_pool()
    state = dict(metadata) if isinstance(metadata, Mapping) else {}

    provenance_rows = await selected_pool.fetch(
        "SELECT document_id,chunk_id,source_sha256,modality,media_id "
        "FROM citation_provenance WHERE kb_name=$1 AND document_id=$2 "
        "AND chunk_id=ANY($3::text[]) AND provenance_version='v1' FOR SHARE",
        kb_name,
        document_id,
        sorted(declared_chunks),
    )
    provenance_by_chunk: dict[str, Any] = {}
    for row in provenance_rows or []:
        chunk_id = str(row["chunk_id"])
        if chunk_id in provenance_by_chunk:
            raise _failure()
        provenance_by_chunk[chunk_id] = row
    if set(provenance_by_chunk) != declared_chunks or any(
        str(row.get("document_id") or "") != document_id
        or str(row.get("source_sha256") or "") != source_sha256
        for row in provenance_by_chunk.values()
    ):
        raise _failure()

    catalog = state.get("odl_media_catalog")
    image_counts = state.get("image_media_counts")
    image_expected = (
        int(image_counts.get("eligible_elements") or 0)
        if isinstance(image_counts, Mapping)
        else 0
    )
    if isinstance(catalog, list) != isinstance(image_counts, Mapping):
        raise _failure()
    if isinstance(catalog, list) and bool(catalog) != (image_expected > 0):
        raise _failure()
    if image_expected:
        if (
            not isinstance(catalog, list)
            or len(catalog) != image_expected
            or state.get("image_media_incomplete") is not False
            or not isinstance(image_counts, Mapping)
            or int(image_counts.get("valid_manifest_media") or 0) != image_expected
            or int(image_counts.get("persisted_image_chunks") or 0) != image_expected
            or int(image_counts.get("catalog_media") or 0) != image_expected
        ):
            raise _failure()
        expected: dict[tuple[str, str], str] = {}
        for entry in catalog:
            if not isinstance(entry, Mapping):
                raise _failure()
            media_id = str(entry.get("media_id") or "")
            chunk_id = str(entry.get("chunk_id") or "")
            if (
                not media_id
                or media_id.startswith("legacy:")
                or entry.get("kb") != kb_name
                or entry.get("document_id") != document_id
                or entry.get("status") != "persisted"
                or chunk_id not in declared_chunks
                or (document_id, chunk_id) in expected
            ):
                raise _failure()
            expected[(document_id, chunk_id)] = media_id
        for key, media_id in expected.items():
            row = provenance_by_chunk.get(key[1])
            if (
                row is None
                or str(row.get("modality") or "") != "image"
                or str(row.get("media_id") or "") != media_id
            ):
                raise _failure()

    if require_video:
        assets = await selected_pool.fetch(
            "SELECT media_id,document_id,source_sha256,server_path,status "
            "FROM video_assets WHERE kb_name=$1 AND document_id=$2 FOR SHARE",
            kb_name,
            document_id,
        )
        if len(assets or []) != 1:
            raise _failure()
        asset = assets[0]
        media_id = str(asset.get("media_id") or "")
        video_path = _controlled_video_path(asset.get("server_path"))
        if (
            not media_id
            or media_id.startswith("legacy:")
            or str(asset.get("document_id") or "") != document_id
            or str(asset.get("source_sha256") or "") != source_sha256
            or asset.get("status") != "ready"
            or video_path is None
            or media_file_sha256(video_path) != source_sha256
        ):
            raise _failure()
        segments = await selected_pool.fetch(
            "SELECT s.segment_id,s.media_id,s.chunk_id,s.source_sha256 AS segment_source_sha256,"
            "s.start_ms,s.end_ms,s.status,"
            "p.document_name,p.source_sha256,p.media_id AS provenance_media_id,"
            "p.segment_id AS provenance_segment_id,p.start_ms AS provenance_start_ms,"
            "p.end_ms AS provenance_end_ms,p.locator_status "
            "FROM video_segments s JOIN citation_provenance p "
            "ON p.kb_name=s.kb_name AND p.document_id=s.document_id "
            "AND p.chunk_id=s.chunk_id AND p.provenance_version='v1' "
            "WHERE s.kb_name=$1 AND s.document_id=$2 "
            "ORDER BY s.segment_index FOR SHARE OF s,p",
            kb_name,
            document_id,
        )
        if not segments:
            raise _failure()
        seen_chunks: set[str] = set()
        for row in segments:
            chunk_id = str(row.get("chunk_id") or "")
            start_ms, end_ms = row.get("start_ms"), row.get("end_ms")
            if (
                not chunk_id
                or chunk_id not in declared_chunks
                or chunk_id in seen_chunks
                or row.get("status") != "ready"
                or str(row.get("media_id") or "") != media_id
                or str(row.get("segment_source_sha256") or "") != source_sha256
                or not str(row.get("segment_id") or "")
                or not isinstance(start_ms, int)
                or not isinstance(end_ms, int)
                or end_ms <= start_ms
                or not str(row.get("document_name") or "")
                or str(row.get("source_sha256") or "") != source_sha256
                or str(row.get("provenance_media_id") or "") != media_id
                or str(row.get("provenance_segment_id") or "")
                != str(row.get("segment_id") or "")
                or row.get("provenance_start_ms") != start_ms
                or row.get("provenance_end_ms") != end_ms
                or row.get("locator_status") != "exact"
            ):
                raise _failure()
            seen_chunks.add(chunk_id)
        if seen_chunks != declared_chunks:
            raise _failure()


def mark_media_delivery_v2(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    result = dict(metadata) if isinstance(metadata, Mapping) else {}
    result["media_delivery_version"] = MEDIA_DELIVERY_VERSION
    return result
