"""Durable citation provenance and path-free public DTO construction."""

from __future__ import annotations

import json
import hashlib
import logging
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from raganything.services.pg_state_repo import get_pg_pool
from raganything.utils import display_document_name


logger = logging.getLogger(__name__)


class CitationProvenanceError(RuntimeError):
    """Raised when a required provenance write cannot be completed."""

    failure_code = "citation_provenance_failed"
    failure_stage = "provenance"


def find_citation_provenance_error(
    exc: BaseException,
) -> CitationProvenanceError | None:
    """Return a provenance failure found anywhere in an exception chain."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, CitationProvenanceError):
            return current
        current = current.__cause__ or current.__context__
    return None

_LOCATOR_STATUSES = frozenset({"exact", "page", "document", "unavailable"})
_SOURCE_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PRIVATE_LABEL_LINE_RE = re.compile(
    r"(?im)^[^\S\r\n]*(?:image\s+path|file_path|server_path|图片路径|图像路径)"
    r"\s*[:：=].*(?:\r?\n|$)"
)
_BRACKETED_IMAGE_PATH_RE = re.compile(
    r"\[\s*(?:图片|图像)路径\s*[:：]\s*[^\]\r\n]*\]", re.IGNORECASE
)
_FILE_URI_RE = re.compile(r"(?i)\bfile://[^\s<>\"']+")
_WINDOWS_PATH_RE = re.compile(
    r"(?i)(?<![\w])(?:[a-z]:[\\/]|\\\\)[^\s<>\"'|\]\)}]+"
)
_UPLOAD_PATH_RE = re.compile(r"(?i)(?<![\w.-])/uploads?(?:/[^\s<>\"'\]\)}]+)*")
_PRIVATE_FIELD_NAME_RE = re.compile(r"(?i)\b(?:file_path|server_path)\b")
_PUBLIC_COORDINATE_STRING_FIELDS = frozenset({
    "type", "name", "units", "unit", "kind", "origin",
})
_PUBLIC_COORDINATE_NUMBER_FIELDS = frozenset({
    "width", "height", "page_width", "page_height", "image_width",
    "image_height",
})
_PUBLIC_FRAME_STRING_FIELDS = frozenset({
    "frame_id", "media_id", "element_id",
})
_PUBLIC_FRAME_NUMBER_FIELDS = frozenset({
    "timestamp_ms", "index", "page", "page_idx", "x", "y", "width",
    "height",
})

_SELECT_COLUMNS = """
    kb_name, document_id, document_name, chunk_id, source_sha256,
    provenance_version, page, page_idx, section_path, modality, media_id,
    segment_id, element_id, figure_label, bbox, bbox_coordinate_system,
    start_ms, end_ms, frame_refs, locator_status, excerpt, ingested_at
"""
_SELECT_REFERENCE_COLUMNS = """
    p.kb_name, p.document_id, p.document_name, p.chunk_id, p.source_sha256,
    p.provenance_version, p.page, p.page_idx, p.section_path, p.modality,
    p.media_id, p.segment_id, p.element_id, p.figure_label, p.bbox,
    p.bbox_coordinate_system, p.start_ms, p.end_ms, p.frame_refs,
    p.locator_status, p.excerpt, p.ingested_at
"""

_UPSERT_SQL = """
    INSERT INTO citation_provenance (
        kb_name, document_id, document_name, chunk_id, source_sha256,
        provenance_version, page, page_idx, section_path, modality, media_id,
        segment_id, element_id, figure_label, bbox, bbox_coordinate_system,
        start_ms, end_ms, frame_refs, locator_status, excerpt, ingested_at,
        metadata
    ) VALUES (
        $1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11,
        $12, $13, $14, $15::jsonb, $16::jsonb, $17, $18, $19::jsonb,
        $20, $21, $22, $23::jsonb
    )
    ON CONFLICT (
        kb_name, document_id, chunk_id, provenance_version
    ) DO UPDATE SET
        document_name = EXCLUDED.document_name,
        source_sha256 = EXCLUDED.source_sha256,
        page = EXCLUDED.page,
        page_idx = EXCLUDED.page_idx,
        section_path = EXCLUDED.section_path,
        modality = EXCLUDED.modality,
        media_id = EXCLUDED.media_id,
        segment_id = EXCLUDED.segment_id,
        element_id = EXCLUDED.element_id,
        figure_label = EXCLUDED.figure_label,
        bbox = EXCLUDED.bbox,
        bbox_coordinate_system = EXCLUDED.bbox_coordinate_system,
        start_ms = EXCLUDED.start_ms,
        end_ms = EXCLUDED.end_ms,
        frame_refs = EXCLUDED.frame_refs,
        locator_status = EXCLUDED.locator_status,
        excerpt = EXCLUDED.excerpt,
        ingested_at = EXCLUDED.ingested_at,
        metadata = EXCLUDED.metadata,
        updated_at = NOW()
"""


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _json_value(value: object, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return default
    return value


def _optional_int(value: object, *, minimum: int = 0) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return normalized if normalized >= minimum else None


def _section_path(value: object) -> list[str]:
    value = _json_value(value, value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [text for item in value if (text := _text(item))]
    text = _text(value)
    return [text] if text else []


def _json_list(value: object) -> list[Any]:
    value = _json_value(value, [])
    return list(value) if isinstance(value, list) else []


def _json_location(value: object) -> dict[str, float] | None:
    value = _json_value(value, None)
    if isinstance(value, Mapping):
        result = dict(value)
        if all(key in result for key in ("left", "bottom", "right", "top")):
            try:
                left, bottom = float(result["left"]), float(result["bottom"])
                right, top = float(result["right"]), float(result["top"])
            except (TypeError, ValueError, OverflowError):
                return None
            if right < left or top < bottom:
                return None
            return {"x": left, "y": bottom, "width": right - left, "height": top - bottom}
        try:
            x = float(result["x"])
            y = float(result["y"])
            width = float(result["width"])
            height = float(result["height"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        if width < 0 or height < 0:
            return None
        return {"x": x, "y": y, "width": width, "height": height}
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        try:
            left, bottom, right, top = (float(item) for item in value[:4])
        except (TypeError, ValueError, OverflowError):
            return None
        if right < left or top < bottom:
            return None
        return {"x": left, "y": bottom, "width": right - left, "height": top - bottom}
    return None


def _coordinate_system(value: object) -> dict[str, Any] | None:
    value = _json_value(value, value)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key in _PUBLIC_COORDINATE_STRING_FIELDS:
            text = _text(value.get(key))
            if text:
                result[key] = text
        for key in _PUBLIC_COORDINATE_NUMBER_FIELDS:
            raw = value.get(key)
            if raw is None or isinstance(raw, bool):
                continue
            try:
                number = float(raw)
            except (TypeError, ValueError, OverflowError):
                continue
            if number >= 0:
                result[key] = number
        order = value.get("order")
        if isinstance(order, Sequence) and not isinstance(
            order, (str, bytes, bytearray)
        ):
            sanitized_order = [
                text for item in order if (text := _text(item))
            ]
            if sanitized_order:
                result["order"] = sanitized_order
        return result or None
    text = _text(value)
    return {"type": text} if text else None


def _frame_refs(value: object) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _json_list(value):
        if not isinstance(item, Mapping):
            continue
        sanitized: dict[str, Any] = {}
        for key in _PUBLIC_FRAME_STRING_FIELDS:
            text = _text(item.get(key))
            if text:
                sanitized[key] = text
        for key in _PUBLIC_FRAME_NUMBER_FIELDS:
            raw = item.get(key)
            if raw is None or isinstance(raw, bool):
                continue
            try:
                sanitized[key] = float(raw)
            except (TypeError, ValueError, OverflowError):
                continue
        if sanitized:
            result.append(sanitized)
    return result


def _iso_timestamp(value: object) -> str | None:
    if isinstance(value, datetime):
        current = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return current.isoformat()
    text = _text(value)
    return text or None


def _storage_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("ingested_at must be an ISO-8601 timestamp") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _locator_status(
    requested: str,
    *,
    document_name: str,
    page: int | None,
    bbox: object,
    media_id: str,
    start_ms: int | None,
    end_ms: int | None,
) -> str:
    if requested in _LOCATOR_STATUSES:
        return requested
    if bbox is not None and media_id:
        return "exact"
    if media_id and start_ms is not None and end_ms is not None:
        return "exact"
    if bbox is not None or page is not None or start_ms is not None or end_ms is not None:
        return "page"
    return "document" if document_name else "unavailable"


def normalize_provenance_record(record: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize parser, video, database, or legacy provenance into one dict."""
    if not isinstance(record, Mapping):
        return {}
    raw = dict(record)
    image = _mapping(raw.get("image") or raw.get("image_provenance"))
    video = _mapping(raw.get("video_segment"))
    page_idx = _optional_int(raw.get("page_idx"), minimum=0)
    page = _optional_int(raw.get("page"), minimum=1)
    trusted_page_idx = (
        raw.get("page_idx_trusted") is True
        or raw.get("page_index_base") == 0
    )
    if page is None and page_idx is not None and trusted_page_idx:
        page = page_idx + 1
    document_name = display_document_name(
        raw.get("document_name")
        or raw.get("source_title")
        or raw.get("source_name")
        or raw.get("title")
        or raw.get("file_path")
    )
    bbox = _json_location(raw.get("bbox", image.get("bbox")))
    media_id = _text(raw.get("media_id") or image.get("media_id") or video.get("media_id"))
    start_ms = _optional_int(raw.get("start_ms", video.get("start_ms")), minimum=0)
    end_ms = _optional_int(raw.get("end_ms", video.get("end_ms")), minimum=0)
    modality = _text(
        raw.get("modality")
        or raw.get("original_type")
        or ("video" if video or start_ms is not None else "image" if image or bbox is not None else "text")
    ).lower() or "text"
    normalized = {
        "kb_name": _text(raw.get("kb_name") or raw.get("kb") or raw.get("media_kb")),
        "document_id": _text(raw.get("document_id") or raw.get("doc_id") or raw.get("full_doc_id")),
        "document_name": document_name,
        "chunk_id": _text(raw.get("chunk_id") or raw.get("chunkId")),
        "source_sha256": _text(raw.get("source_sha256")).lower(),
        "provenance_version": _text(raw.get("provenance_version") or "v1"),
        "page": page,
        "page_idx": page_idx,
        "section_path": _section_path(raw.get("section_path", raw.get("section", raw.get("_section_path")))),
        "modality": modality,
        "media_id": media_id,
        "segment_id": _text(raw.get("segment_id") or video.get("segment_id") or video.get("id")),
        "element_id": _text(raw.get("element_id") or image.get("element_id") or image.get("elementId")),
        "figure_label": _text(raw.get("figure_label") or image.get("figure_label") or image.get("figure") or image.get("label")),
        "bbox": bbox,
        "bbox_coordinate_system": _coordinate_system(
            raw.get("bbox_coordinate_system", image.get("bbox_coordinate_system", image.get("coordinate_system")))
        ),
        "start_ms": start_ms,
        "end_ms": end_ms,
        "frame_refs": _frame_refs(raw.get("frame_refs", video.get("frame_refs"))),
        "locator_status": "",
        "excerpt": _text(raw.get("excerpt") or raw.get("content") or raw.get("text")),
        "ingested_at": _iso_timestamp(raw.get("ingested_at") or raw.get("created_at")),
    }
    normalized["locator_status"] = _locator_status(
        _text(raw.get("locator_status")),
        document_name=document_name,
        page=page,
        bbox=bbox,
        media_id=media_id,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    return normalized


def _redact_excerpt(value: object) -> str:
    text = _text(value)
    if not text:
        return ""
    text = _PRIVATE_LABEL_LINE_RE.sub("", text)
    text = _BRACKETED_IMAGE_PATH_RE.sub("", text)
    text = _FILE_URI_RE.sub("", text)
    text = _WINDOWS_PATH_RE.sub("", text)
    text = _UPLOAD_PATH_RE.sub("", text)
    text = _PRIVATE_FIELD_NAME_RE.sub("path", text)
    return "\n".join(line.rstrip() for line in text.splitlines() if line.strip()).strip()


def _compact(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in values.items()
        if value is not None and value != "" and value != []
    }


def _public_video_segments(
    values: object,
    *,
    media_id: str,
    media_kb: str,
) -> list[dict[str, Any]]:
    """Whitelist, validate, sort, and deduplicate public video ranges."""
    if isinstance(values, Mapping):
        values = [values]
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return []
    ranges: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for value in values:
        if not isinstance(value, Mapping):
            continue
        value_media_id = _text(value.get("media_id") or media_id)
        value_media_kb = _text(value.get("media_kb") or value.get("kb") or media_kb)
        segment_id = _text(value.get("segment_id") or value.get("id"))
        start_ms = _optional_int(
            value.get("start_ms", value.get("start_ts")), minimum=0
        )
        end_ms = _optional_int(
            value.get("end_ms", value.get("end_ts")), minimum=0
        )
        if (
            not media_id or value_media_id != media_id
            or not media_kb or value_media_kb != media_kb
            or not segment_id or start_ms is None or end_ms is None
            or start_ms < 0 or end_ms <= start_ms
        ):
            continue
        identity = (segment_id, start_ms, end_ms)
        if identity in seen:
            continue
        seen.add(identity)
        ranges.append(_compact({
            "media_id": media_id,
            "media_kb": media_kb,
            "segment_id": segment_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "frame_refs": _frame_refs(value.get("frame_refs")),
        }))
    return sorted(
        ranges,
        key=lambda item: (item["start_ms"], item["end_ms"], item["segment_id"]),
    )


def build_provenance_citation(
    record: Mapping[str, Any] | None,
    *,
    excerpt: str = "",
    citation_id: str | None = None,
    **safe_overrides: Any,
) -> dict[str, Any]:
    """Build a path-free public citation DTO from trusted provenance fields."""
    raw = dict(record) if isinstance(record, Mapping) else {}
    for field in (
        "document_id", "document_name", "chunk_id", "page", "page_idx",
        "section_path", "modality", "media_id", "segment_id", "element_id",
        "figure_label", "bbox", "bbox_coordinate_system", "start_ms", "end_ms",
        "frame_refs", "locator_status", "kb_name",
    ):
        if field in safe_overrides:
            raw[field] = safe_overrides[field]
    if isinstance(safe_overrides.get("image"), Mapping):
        raw["image"] = dict(safe_overrides["image"])
    if isinstance(safe_overrides.get("video_segment"), Mapping):
        raw["video_segment"] = dict(safe_overrides["video_segment"])

    normalized = normalize_provenance_record(raw)
    if not normalized or not (
        normalized.get("document_id")
        or normalized.get("document_name")
        or normalized.get("chunk_id")
        or normalized.get("media_id")
    ):
        return {}
    public = {
        "document_id": normalized["document_id"],
        "document_name": normalized["document_name"],
        "chunk_id": normalized["chunk_id"],
        "page": normalized["page"],
        "section_path": normalized["section_path"],
        "modality": normalized["modality"],
        "locator_status": normalized["locator_status"],
        "excerpt": _redact_excerpt(excerpt or safe_overrides.get("excerpt") or normalized.get("excerpt")),
    }
    identifier = _text(citation_id or safe_overrides.get("citation_id") or raw.get("citation_id"))
    if identifier:
        public["citation_id"] = identifier
    for field in (
        "index", "source_title", "reliability", "ingested_at", "legacy_status"
    ):
        value = safe_overrides.get(field, raw.get(field))
        if value not in (None, ""):
            if field == "source_title":
                public[field] = display_document_name(value)
            elif field == "ingested_at":
                public[field] = _iso_timestamp(value)
            else:
                public[field] = value

    media_id = normalized["media_id"]
    kb_name = normalized["kb_name"]
    if media_id:
        public["media_id"] = media_id
    if normalized["start_ms"] is not None:
        public["start_ms"] = normalized["start_ms"]
    if normalized["end_ms"] is not None:
        public["end_ms"] = normalized["end_ms"]
    if normalized["segment_id"]:
        public["segment_id"] = normalized["segment_id"]

    is_video = normalized["modality"] == "video" or bool(
        normalized["segment_id"] or normalized["start_ms"] is not None
    )
    if is_video:
        primary_segment = _compact({
            "media_id": media_id,
            "media_kb": kb_name,
            "segment_id": normalized["segment_id"],
            "start_ms": normalized["start_ms"],
            "end_ms": normalized["end_ms"],
            "frame_refs": normalized["frame_refs"],
        })
        raw_segments: list[object] = []
        if primary_segment:
            raw_segments.append(primary_segment)
        override_segments = safe_overrides.get(
            "video_segments", raw.get("video_segments")
        )
        if isinstance(override_segments, Mapping):
            raw_segments.append(override_segments)
        elif isinstance(override_segments, Sequence) and not isinstance(
            override_segments, (str, bytes)
        ):
            raw_segments.extend(override_segments)
        segments = _public_video_segments(
            raw_segments,
            media_id=media_id,
            media_kb=kb_name,
        )
        if segments:
            public["video_segment"] = segments[0]
            public["video_segments"] = segments
        if media_id and kb_name:
            from raganything.services.video_segments import controlled_video_media_url

            public["media_kb"] = kb_name
            public["media_url"] = controlled_video_media_url(media_id, kb_name)
    elif media_id or normalized["element_id"] or normalized["bbox"] is not None:
        image = _compact({
            "media_id": media_id,
            "element_id": normalized["element_id"],
            "figure_label": normalized["figure_label"],
            "bbox": normalized["bbox"],
            "bbox_coordinate_system": normalized["bbox_coordinate_system"],
        })
        if media_id and kb_name:
            from raganything.services.odl_media_delivery import controlled_odl_media_url

            image["media_url"] = controlled_odl_media_url(media_id, kb_name)
        if image:
            public["image"] = image
    return public


def _storage_record(record: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[Any, ...]]:
    normalized = normalize_provenance_record(record)
    for field in ("kb_name", "document_id", "chunk_id"):
        if not normalized[field]:
            raise ValueError(f"{field} is required")
    if not _SOURCE_SHA256_RE.fullmatch(normalized["source_sha256"]):
        raise ValueError("source_sha256 must be 64 lowercase hexadecimal characters")
    if not normalized["provenance_version"] or len(normalized["provenance_version"]) > 64:
        raise ValueError("provenance_version must be 1-64 characters")
    if (
        normalized["page"] is not None
        and normalized["page_idx"] is not None
        and normalized["page"] != normalized["page_idx"] + 1
    ):
        raise ValueError("page must equal page_idx + 1 when both are provided")
    start_ms, end_ms = normalized["start_ms"], normalized["end_ms"]
    if (start_ms is None) != (end_ms is None) or (
        start_ms is not None and end_ms is not None and end_ms <= start_ms
    ):
        raise ValueError("start_ms and end_ms must form a positive time range")
    raw = dict(record)
    metadata = _json_value(raw.get("metadata"), {})
    if not isinstance(metadata, Mapping):
        raise ValueError("metadata must be an object")
    args = (
        normalized["kb_name"], normalized["document_id"], normalized["document_name"],
        normalized["chunk_id"], normalized["source_sha256"], normalized["provenance_version"],
        normalized["page"], normalized["page_idx"],
        json.dumps(normalized["section_path"], ensure_ascii=False), normalized["modality"],
        normalized["media_id"] or None, normalized["segment_id"] or None,
        normalized["element_id"] or None, normalized["figure_label"] or None,
        json.dumps(normalized["bbox"], ensure_ascii=False) if normalized["bbox"] is not None else None,
        json.dumps(normalized["bbox_coordinate_system"], ensure_ascii=False)
        if normalized["bbox_coordinate_system"] is not None else None,
        start_ms, end_ms, json.dumps(normalized["frame_refs"], ensure_ascii=False),
        normalized["locator_status"], normalized["excerpt"],
        _storage_timestamp(raw.get("ingested_at") or raw.get("created_at")),
        json.dumps(dict(metadata), ensure_ascii=False),
    )
    return normalized, args


@asynccontextmanager
async def _connection(pool: Any):
    acquire = getattr(pool, "acquire", None)
    if acquire is None:
        yield pool
        return
    async with acquire() as conn:
        yield conn


@asynccontextmanager
async def _transaction(conn: Any):
    factory = getattr(conn, "transaction", None)
    if factory is None:
        yield
        return
    async with factory():
        yield


async def upsert_provenance_records(
    records: Sequence[Mapping[str, Any]], *, pool: Any = None,
) -> list[dict[str, Any]]:
    """Atomically replace the current provenance rows for a record batch."""
    prepared: dict[tuple[str, str, str, str], tuple[dict[str, Any], tuple[Any, ...]]] = {}
    for record in records:
        normalized, args = _storage_record(record)
        key = (
            normalized["kb_name"], normalized["document_id"],
            normalized["chunk_id"], normalized["provenance_version"],
        )
        prepared[key] = (normalized, args)
    if not prepared:
        return []
    selected_pool = pool if pool is not None else get_pg_pool()
    async with _connection(selected_pool) as conn:
        async with _transaction(conn):
            for _normalized, args in prepared.values():
                await conn.execute(_UPSERT_SQL, *args)
    return [normalized for normalized, _args in prepared.values()]


async def upsert_provenance(
    record: Mapping[str, Any], *, pool: Any = None,
) -> dict[str, Any]:
    """Upsert one record; write failures deliberately propagate to the caller."""
    return (await upsert_provenance_records([record], pool=pool))[0]


upsert_provenance_record = upsert_provenance


async def _fetch_rows(pool: Any, sql: str, *args: Any) -> list[dict[str, Any]]:
    async with _connection(pool) as conn:
        rows = await conn.fetch(sql, *args)
    return [dict(row) for row in rows or []]


async def batch_get_provenance(
    kb_name: str, chunk_ids: Sequence[str], *, pool: Any = None,
) -> dict[str, dict[str, Any]]:
    """Return unambiguous current rows keyed by chunk ID; reads fail soft."""
    ids = list(dict.fromkeys(_text(value) for value in chunk_ids if _text(value)))
    if not _text(kb_name) or not ids:
        return {}
    try:
        selected_pool = pool if pool is not None else get_pg_pool()
        rows = await _fetch_rows(
            selected_pool,
            f"SELECT {_SELECT_COLUMNS} FROM citation_provenance "
            "WHERE kb_name=$1 AND chunk_id=ANY($2::text[]) "
            "ORDER BY chunk_id, document_id, updated_at DESC, id DESC",
            _text(kb_name), ids,
        )
    except Exception as exc:
        logger.debug("citation provenance batch read unavailable: %s", type(exc).__name__)
        return {}
    candidates: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        chunk_id, document_id = _text(row.get("chunk_id")), _text(row.get("document_id"))
        if chunk_id and document_id and document_id not in candidates[chunk_id]:
            candidates[chunk_id][document_id] = normalize_provenance_record(row)
    return {
        chunk_id: next(iter(by_document.values()))
        for chunk_id, by_document in candidates.items()
        if len(by_document) == 1
    }


async def batch_get_provenance_for_references(
    kb_name: str,
    references: Sequence[Mapping[str, Any]],
    *,
    pool: Any = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Return exact current rows keyed by ``(document_id, chunk_id)``."""
    pairs = list(dict.fromkeys(
        (_text(item.get("document_id")), _text(item.get("chunk_id")))
        for item in references if isinstance(item, Mapping)
        if _text(item.get("document_id")) and _text(item.get("chunk_id"))
    ))
    if not _text(kb_name) or not pairs:
        return {}
    try:
        selected_pool = pool if pool is not None else get_pg_pool()
        rows = await _fetch_rows(
            selected_pool,
            f"WITH requested AS ("
            "SELECT * FROM unnest($2::text[], $3::text[]) "
            "AS item(document_id, chunk_id)) "
            f"SELECT {_SELECT_REFERENCE_COLUMNS} FROM citation_provenance p "
            "JOIN requested r ON r.document_id=p.document_id AND r.chunk_id=p.chunk_id "
            "WHERE p.kb_name=$1 "
            "ORDER BY p.document_id, p.chunk_id, p.updated_at DESC, p.id DESC",
            _text(kb_name), [item[0] for item in pairs], [item[1] for item in pairs],
        )
    except Exception as exc:
        logger.debug("citation provenance reference read unavailable: %s", type(exc).__name__)
        return {}
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (_text(row.get("document_id")), _text(row.get("chunk_id")))
        if all(key) and key not in result:
            result[key] = normalize_provenance_record(row)
    return result


def _is_undefined_table_error(exc: BaseException) -> bool:
    """Recognize only PostgreSQL's precise undefined-table condition."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "sqlstate", None) == "42P01":
            return True
        current = current.__cause__ or current.__context__
    return False


async def _delete_provenance(
    sql: str,
    args: tuple[Any, ...],
    pool: Any,
    *,
    fail_soft: bool = False,
) -> int:
    try:
        selected_pool = pool if pool is not None else get_pg_pool()
        async with _connection(selected_pool) as conn:
            async with _transaction(conn):
                status = await conn.execute(sql, *args)
        return int(str(status).rsplit(" ", 1)[-1])
    except Exception as exc:
        if fail_soft and _is_undefined_table_error(exc):
            logger.debug(
                "citation provenance table is unavailable in legacy schema: %s",
                type(exc).__name__,
            )
            return 0
        raise


async def delete_document_provenance(
    kb_name: str,
    document_id: str,
    *,
    pool: Any = None,
    fail_soft: bool = False,
) -> int:
    """Delete document provenance, propagating failures unless legacy fallback is explicit."""
    return await _delete_provenance(
        "DELETE FROM citation_provenance WHERE kb_name=$1 AND document_id=$2",
        (_text(kb_name), _text(document_id)), pool, fail_soft=fail_soft,
    )


async def delete_kb_provenance(
    kb_name: str,
    *,
    pool: Any = None,
    fail_soft: bool = False,
) -> int:
    """Delete one KB's provenance, with opt-in pre-038 compatibility."""
    return await _delete_provenance(
        "DELETE FROM citation_provenance WHERE kb_name=$1",
        (_text(kb_name),), pool, fail_soft=fail_soft,
    )


async def delete_chunk_provenance(
    kb_name: str,
    document_id: str,
    chunk_id: str,
    *,
    pool: Any = None,
    fail_soft: bool = False,
) -> int:
    """Delete chunk provenance, propagating failures unless legacy fallback is explicit."""
    return await _delete_provenance(
        "DELETE FROM citation_provenance "
        "WHERE kb_name=$1 AND document_id=$2 AND chunk_id=$3",
        (_text(kb_name), _text(document_id), _text(chunk_id)), pool,
        fail_soft=fail_soft,
    )


async def replace_chunk_provenance(
    kb_name: str,
    document_id: str,
    old_chunk_id: str,
    new_chunk_id: str,
    *,
    document_name: str,
    excerpt: str,
    source_sha256: str | None = None,
    pool: Any = None,
    fail_soft: bool = False,
) -> dict[str, Any] | None:
    """Atomically replace an edited chunk's lineage with document-level provenance."""
    selected_pool = pool if pool is not None else get_pg_pool()
    try:
        async with _connection(selected_pool) as conn:
            async with _transaction(conn):
                previous = await conn.fetchrow(
                    "SELECT source_sha256 FROM citation_provenance "
                    "WHERE kb_name=$1 AND document_id=$2 AND chunk_id=$3 "
                    "AND provenance_version='v1' FOR UPDATE",
                    _text(kb_name), _text(document_id), _text(old_chunk_id),
                )
                previous = dict(previous) if previous else {}
                explicit_hash = _text(source_sha256).lower()
                if explicit_hash and not _SOURCE_SHA256_RE.fullmatch(explicit_hash):
                    raise ValueError(
                        "source_sha256 must be 64 lowercase hexadecimal characters"
                    )
                inherited_hash = _text(previous.get("source_sha256")).lower()
                effective_hash = explicit_hash or inherited_hash
                source_kind = "document_source"
                if not effective_hash:
                    payload = json.dumps(
                        [
                            "manual-edit-v1",
                            _text(kb_name),
                            _text(document_id),
                            _text(new_chunk_id),
                            str(excerpt or ""),
                        ],
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    effective_hash = hashlib.sha256(payload).hexdigest()
                    source_kind = "manual_edit"

                normalized, args = _storage_record({
                    "kb_name": kb_name,
                    "document_id": document_id,
                    "document_name": display_document_name(document_name),
                    "chunk_id": new_chunk_id,
                    "source_sha256": effective_hash,
                    "provenance_version": "v1",
                    "section_path": [],
                    "modality": "text",
                    "locator_status": "document",
                    "excerpt": str(excerpt or "")[:1000],
                    "metadata": {
                        "origin": "manual_edit",
                        "source_kind": source_kind,
                        "previous_chunk_id": _text(old_chunk_id),
                    },
                })
                await conn.execute(_UPSERT_SQL, *args)
                if _text(new_chunk_id) != _text(old_chunk_id):
                    await conn.execute(
                        "DELETE FROM citation_provenance "
                        "WHERE kb_name=$1 AND document_id=$2 AND chunk_id=$3",
                        _text(kb_name), _text(document_id), _text(old_chunk_id),
                    )
        return normalized
    except Exception as exc:
        if fail_soft and _is_undefined_table_error(exc):
            logger.debug(
                "citation provenance table is unavailable in legacy schema: %s",
                type(exc).__name__,
            )
            return None
        raise


__all__ = [
    "batch_get_provenance",
    "batch_get_provenance_for_references",
    "build_provenance_citation",
    "CitationProvenanceError",
    "find_citation_provenance_error",
    "delete_chunk_provenance",
    "delete_document_provenance",
    "delete_kb_provenance",
    "normalize_provenance_record",
    "replace_chunk_provenance",
    "upsert_provenance",
    "upsert_provenance_record",
    "upsert_provenance_records",
]
