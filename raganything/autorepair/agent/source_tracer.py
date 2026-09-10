"""AutoRepair citation extraction and provenance compatibility helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from typing import Any
from urllib.parse import unquote, urlsplit

from raganything.citation_parser import extract_citations as _base_extract_citations
from raganything.utils import display_document_name

logger = logging.getLogger(__name__)

_LOCATOR_STATUSES = {"exact", "page", "document", "unavailable"}
_SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"(?i)data:image/[^\s,;]+;base64,[A-Za-z0-9+/=_-]+"),
    re.compile(r"(?i)file://[^\r\n\s<>\"']+"),
    re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[^\r\n<>\"']+"),
    re.compile(r"/(?:home|Users|var|tmp|etc|root|opt|mnt)/[^\r\n<>\"']+"),
)
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:@+-]{1,512}$")
_FRAGMENT_SUFFIX_RE = re.compile(r"\s*\(片段\d+\)\s*$")


def _sanitize_text(value: object, *, limit: int = 2000) -> str:
    text = value if isinstance(value, str) else str(value or "")
    for pattern in _SENSITIVE_TEXT_PATTERNS:
        text = pattern.sub("[redacted-media-reference]", text)
    return text.strip()[:limit]


def _safe_identifier(value: object) -> str | None:
    text = str(value or "").strip()
    return text if text and _SAFE_IDENTIFIER_RE.fullmatch(text) else None


def _safe_public_url(value: object) -> str:
    """Keep compatibility URL fields without exposing paths or tokenized URLs."""
    if not isinstance(value, str) or not value.strip():
        return ""
    raw = value.strip()
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    decoded_path = unquote(parsed.path)
    if ".." in decoded_path.split("/") or "\\" in decoded_path:
        return ""
    if parsed.scheme in {"http", "https"} and parsed.netloc and not parsed.username:
        return raw if not parsed.query and not parsed.fragment else ""
    if not parsed.scheme and not parsed.netloc and decoded_path.startswith(
        ("/api/knowledge/media/", "/knowledge/media/")
    ):
        return raw
    return ""


def _normalize_page(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        page = int(value)
    except (TypeError, ValueError):
        return None
    return page if page >= 1 else None


def _trusted_page(record: dict[str, Any]) -> int | None:
    page = _normalize_page(record.get("page", record.get("page_number")))
    if page is not None:
        return page
    page_idx = record.get("page_idx")
    base = record.get("page_idx_base", record.get("page_index_base"))
    if page_idx is None or base not in (0, "0"):
        return None
    try:
        index = int(page_idx)
    except (TypeError, ValueError):
        return None
    return index + 1 if index >= 0 else None


def _normalize_section_path(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [text for item in values if (text := _sanitize_text(item, limit=300))]


def _finite_number(value: object) -> float | int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def _normalize_bbox(value: object) -> dict[str, float | int] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        x, y, width, height = value[:4]
    elif isinstance(value, dict):
        x, y = value.get("x", value.get("left")), value.get("y", value.get("top"))
        width, height = value.get("width"), value.get("height")
        if width is None and value.get("right") is not None:
            left, right = _finite_number(x), _finite_number(value.get("right"))
            width = right - left if left is not None and right is not None else None
        if height is None and value.get("bottom") is not None:
            top, bottom = _finite_number(y), _finite_number(value.get("bottom"))
            height = bottom - top if top is not None and bottom is not None else None
    else:
        return None
    normalized = [_finite_number(item) for item in (x, y, width, height)]
    if any(item is None for item in normalized) or normalized[2] < 0 or normalized[3] < 0:
        return None
    return dict(zip(("x", "y", "width", "height"), normalized))


def _normalize_coordinate_system(value: object) -> dict[str, Any] | None:
    if isinstance(value, str):
        text = _sanitize_text(value, limit=80)
        return {"type": text} if text else None
    if not isinstance(value, dict):
        return None
    result: dict[str, Any] = {}
    for key in ("type", "name", "unit", "kind", "origin", "y_axis"):
        if text := _sanitize_text(value.get(key), limit=80):
            result[key] = text
    for key in ("width", "height", "page_width", "page_height", "image_width", "image_height"):
        if (number := _finite_number(value.get(key))) is not None:
            result[key] = number
    return result or None


def _normalize_frame_refs(value: object) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        safe: dict[str, Any] = {}
        for key in ("frame_id", "media_id", "element_id"):
            if identifier := _safe_identifier(item.get(key)):
                safe[key] = identifier
        for key in ("timestamp_ms", "start_ms", "end_ms"):
            if (number := _finite_number(item.get(key))) is not None and number >= 0:
                safe[key] = int(number)
        if safe:
            result.append(safe)
    return result


def _shared_builder(
    record: dict[str, Any],
    *,
    excerpt: str,
    citation_id: str | None,
    kb_name: str | None,
) -> dict[str, Any]:
    """Use the project builder when available, with a local rollout fallback."""
    try:
        from raganything.services.provenance import build_provenance_citation
    except (ImportError, AttributeError):
        return {}
    overrides = {"kb_name": kb_name} if kb_name else {}
    try:
        built = build_provenance_citation(
            record,
            excerpt=excerpt,
            citation_id=citation_id,
            **overrides,
        )
    except (KeyError, TypeError, ValueError):
        logger.debug("Shared provenance builder rejected an AutoRepair legacy citation")
        return {}
    return built if isinstance(built, dict) else {}


def normalize_citation_dto(
    citation: dict[str, Any],
    *,
    source_doc: dict[str, Any] | None = None,
    position: int = 0,
    kb_name: str | None = None,
) -> dict[str, Any]:
    """Convert a legacy or persisted citation to the unified, path-free DTO."""
    source_doc = source_doc if isinstance(source_doc, dict) else {}
    record = {**source_doc, **citation}
    excerpt = _sanitize_text(
        citation.get("excerpt")
        or source_doc.get("excerpt")
        or source_doc.get("content")
        or source_doc.get("text"),
        limit=1000,
    )
    requested_id = _safe_identifier(record.get("citation_id"))
    shared = _shared_builder(
        record,
        excerpt=excerpt,
        citation_id=requested_id,
        kb_name=kb_name,
    )
    merged = {**record, **shared}

    raw_name = (
        merged.get("document_name")
        or merged.get("source_title")
        or merged.get("title")
        or merged.get("source")
    )
    document_name = display_document_name(raw_name, default="")
    document_name = _FRAGMENT_SUFFIX_RE.sub("", document_name).strip()
    nested_video = (
        merged.get("video_segment")
        if isinstance(merged.get("video_segment"), dict)
        else {}
    )
    document_id = _safe_identifier(
        merged.get("document_id")
        or merged.get("full_doc_id")
        or merged.get("doc_id")
        or nested_video.get("document_id")
    )
    chunk_id = _safe_identifier(merged.get("chunk_id") or merged.get("chunkId"))
    page = _trusted_page(merged)
    section_path = _normalize_section_path(
        merged.get("section_path", merged.get("section", merged.get("section_title")))
    )

    nested_image = merged.get("image") if isinstance(merged.get("image"), dict) else {}
    media_id = _safe_identifier(
        nested_image.get("media_id")
        or nested_video.get("media_id")
        or merged.get("media_id")
    )
    element_id = _safe_identifier(nested_image.get("element_id") or merged.get("element_id"))
    figure_label = _sanitize_text(
        nested_image.get("figure_label") or merged.get("figure_label"), limit=120
    )
    bbox = _normalize_bbox(nested_image.get("bbox", merged.get("bbox")))
    coordinate_system = _normalize_coordinate_system(
        nested_image.get(
            "bbox_coordinate_system", merged.get("bbox_coordinate_system")
        )
    )
    image_url = _safe_public_url(
        nested_image.get("media_url")
        or nested_image.get("url")
        or merged.get("media_url")
    )

    segment_id = _safe_identifier(
        nested_video.get("segment_id") or merged.get("segment_id")
    )
    start_ms = _finite_number(nested_video.get("start_ms", merged.get("start_ms")))
    end_ms = _finite_number(nested_video.get("end_ms", merged.get("end_ms")))
    if start_ms is not None and start_ms < 0:
        start_ms = None
    if end_ms is not None and end_ms < 0:
        end_ms = None
    frame_refs = _normalize_frame_refs(
        nested_video.get("frame_refs", merged.get("frame_refs"))
    )

    raw_modality = str(merged.get("modality") or "").strip().lower()
    has_video = bool(segment_id or start_ms is not None or end_ms is not None)
    has_image = bool(media_id and (element_id or figure_label or bbox or raw_modality == "image"))
    modality = raw_modality if raw_modality in {"text", "image", "video", "table", "audio"} else ""
    if not modality:
        modality = "video" if has_video else "image" if has_image else "text"

    image = None
    if modality == "image" or has_image:
        image = {
            "media_id": media_id,
            "media_url": image_url or None,
            "element_id": element_id,
            "figure_label": figure_label or None,
            "bbox": bbox,
            "bbox_coordinate_system": coordinate_system,
        }

    video_segment = None
    if modality == "video" or has_video:
        video_segment = {
            "media_id": media_id,
            "media_kb": _safe_identifier(
                kb_name or merged.get("media_kb") or merged.get("kb_name")
            ),
            "segment_id": segment_id,
            "start_ms": int(start_ms) if start_ms is not None else None,
            "end_ms": int(end_ms) if end_ms is not None else None,
            "frame_refs": frame_refs,
        }

    locator_status = str(merged.get("locator_status") or "").strip().lower()
    if locator_status not in _LOCATOR_STATUSES:
        if video_segment and start_ms is not None and end_ms is not None:
            locator_status = "exact"
        elif image and bbox and page is not None:
            locator_status = "exact"
        elif page is not None:
            locator_status = "page"
        elif document_name:
            locator_status = "document"
        else:
            locator_status = "unavailable"

    if not requested_id:
        identity = "|".join(
            str(value or "")
            for value in (document_id, chunk_id, media_id, segment_id, page, position)
        )
        requested_id = f"cit-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}"

    safe_url = _safe_public_url(merged.get("url"))
    if not safe_url and image_url:
        safe_url = image_url
    result: dict[str, Any] = {
        "citation_id": requested_id,
        "document_id": document_id,
        "document_name": document_name or None,
        "chunk_id": chunk_id,
        "excerpt": excerpt,
        "page": page,
        "section_path": section_path,
        "modality": modality,
        "image": image,
        "video_segment": video_segment,
        "locator_status": locator_status,
        # AutoRepair legacy compatibility fields.
        "source_title": document_name,
        "section": _sanitize_text(
            merged.get("section") or (section_path[-1] if section_path else ""),
            limit=300,
        ),
        "reliability": _sanitize_text(merged.get("reliability") or "low", limit=20),
        "url": safe_url,
        "ingested_at": _sanitize_text(
            merged.get("ingested_at") or merged.get("created_at"), limit=80
        ),
    }
    reference_index = merged.get("reference_index", merged.get("index"))
    try:
        if reference_index is not None and int(reference_index) >= 1:
            result["index"] = int(reference_index)
    except (TypeError, ValueError):
        pass
    if media_id:
        result["media_id"] = media_id
    media_kb = _safe_identifier(
        kb_name or merged.get("media_kb") or merged.get("kb_name")
    )
    if media_kb:
        result["media_kb"] = media_kb
    if image_url:
        result["media_url"] = image_url
    raw_ranges = merged.get("video_segments")
    if isinstance(raw_ranges, list) and video_segment:
        ranges = []
        seen_ranges: set[tuple[str, int, int]] = set()
        for item in raw_ranges:
            if not isinstance(item, dict):
                continue
            item_media_id = _safe_identifier(item.get("media_id") or media_id)
            item_media_kb = _safe_identifier(
                item.get("media_kb") or item.get("kb") or media_kb
            )
            item_segment_id = _safe_identifier(
                item.get("segment_id") or item.get("segmentId")
            )
            item_start = _finite_number(item.get("start_ms", item.get("start_ts")))
            item_end = _finite_number(item.get("end_ms", item.get("end_ts")))
            if (
                item_media_id != media_id or item_media_kb != media_kb
                or not item_segment_id or item_start is None or item_end is None
                or item_start < 0 or item_end <= item_start
            ):
                continue
            identity = (item_segment_id, int(item_start), int(item_end))
            if identity in seen_ranges:
                continue
            seen_ranges.add(identity)
            ranges.append({
                "media_id": media_id,
                "media_kb": media_kb,
                "segment_id": item_segment_id,
                "start_ms": int(item_start),
                "end_ms": int(item_end),
                "frame_refs": _normalize_frame_refs(item.get("frame_refs")),
            })
        if ranges:
            result["video_segments"] = sorted(
                ranges,
                key=lambda item: (
                    item["start_ms"], item["end_ms"], item["segment_id"]
                ),
            )
    return result


def normalize_citation_list(
    value: object, *, kb_name: str | None = None
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        normalize_citation_dto(item, position=index, kb_name=kb_name)
        for index, item in enumerate(value)
        if isinstance(item, dict)
    ]


class SourceTracer:
    """Extract answer references while preserving the AutoRepair legacy API."""

    def __init__(self):
        self._citation_cache: dict[str, list[dict]] = {}

    @staticmethod
    def _find_source_doc(
        citation: dict[str, Any], source_docs: list[dict]
    ) -> dict[str, Any] | None:
        raw_index = citation.get("index")
        if isinstance(raw_index, int):
            index = raw_index - 1
            return source_docs[index] if 0 <= index < len(source_docs) else None
        citation_name = display_document_name(citation.get("document_name") or raw_index)
        for candidate in source_docs:
            candidate_label = str(candidate.get("citation_label") or "").strip("[]")
            candidate_name = display_document_name(
                candidate.get("document_name")
                or candidate.get("title")
                or candidate.get("source")
            )
            if citation_name in {candidate_label.removeprefix("来源 "), candidate_name}:
                return candidate
            if _FRAGMENT_SUFFIX_RE.sub("", citation_name) == candidate_name:
                return candidate
        return None

    def extract_citations(self, answer: str, source_docs: list[dict]) -> list[dict]:
        """Extract citations and return unified DTOs plus legacy fields."""
        safe_docs = [item for item in source_docs if isinstance(item, dict)]
        parsed = _base_extract_citations(answer, source_docs=safe_docs)
        citations = parsed["sources"] if isinstance(parsed, dict) else parsed
        result: list[dict[str, Any]] = []
        seen: set[tuple[str | None, str | None, str]] = set()
        for position, citation in enumerate(citations):
            if not isinstance(citation, dict):
                continue
            doc = self._find_source_doc(citation, safe_docs) or {}
            enriched = {
                **citation,
                "document_name": citation.get("document_name")
                or doc.get("document_name")
                or doc.get("title")
                or doc.get("source"),
                "excerpt": citation.get("excerpt")
                or (doc.get("content", doc.get("text", "")) or "")[:200],
                "reliability": self._assess_reliability(doc),
            }
            dto = normalize_citation_dto(enriched, source_doc=doc, position=position)
            key = (dto.get("document_id"), dto.get("chunk_id"), dto["citation_id"])
            if key in seen:
                continue
            seen.add(key)
            result.append(dto)
        return result

    def trace_fact(self, statement: str, knowledge_base: list[dict]) -> list[dict]:
        sources = []
        words = set(statement.lower().split())
        if not words:
            return sources
        for doc in knowledge_base:
            content = doc.get("content", doc.get("text", ""))
            if not content:
                continue
            content_lower = content.lower()
            matches = sum(1 for word in words if word in content_lower)
            if matches >= len(words) * 0.5:
                dto = normalize_citation_dto(
                    {
                        "document_name": doc.get("title", doc.get("document_name")),
                        "excerpt": content[:300],
                        "reliability": self._assess_reliability(doc),
                    },
                    source_doc=doc,
                    position=len(sources),
                )
                dto["match_score"] = matches / len(words)
                sources.append(dto)
        sources.sort(key=lambda item: item["match_score"], reverse=True)
        return sources

    def verify_citations(self, answer: str, citations: list[dict]) -> dict:
        issues = []
        for index, citation in enumerate(citations):
            if not citation.get("source_title") and not citation.get("document_name"):
                issues.append(f"引用 {index + 1} 缺少来源标题")
            if not citation.get("excerpt"):
                issues.append(f"引用 {index + 1} 缺少摘录内容")
        complete = [
            item
            for item in citations
            if (item.get("source_title") or item.get("document_name"))
            and item.get("excerpt")
        ]
        completeness = len(complete) / len(citations) if citations else 1.0
        return {
            "valid": not issues,
            "issues": issues,
            "completeness": round(completeness, 2),
            "total_citations": len(citations),
        }

    @staticmethod
    def _assess_reliability(doc: dict) -> str:
        copyright_status = doc.get("copyright_status", "")
        quality_score = doc.get("quality_score", 0)
        if copyright_status == "authorized" and quality_score >= 80:
            return "high"
        if quality_score >= 60:
            return "medium"
        return "low"
