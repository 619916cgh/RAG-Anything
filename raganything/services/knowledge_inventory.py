"""Authorized knowledge-base inventory derived from document summary records."""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePath
from typing import Any

from raganything.services.document_tagging import get_document_tag_health
from raganything.services.kb_service import load_document_summary_records, pg_list_uploads
from raganything.services.state_service import get_all_tasks, processing_tasks


_RETRIEVABLE_STATUSES = {"processed", "completed"}
_TAG_PROCESSING_STATUSES = {"pending", "running", "retry_wait"}
_FAILED_STATUSES = {"failed", "cancelled", "canceled", "deleted"}
_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv", ".m4v"}
_TYPE_BY_EXTENSION = {
    ".pdf": "pdf",
    ".doc": "document",
    ".docx": "document",
    ".txt": "document",
    ".md": "document",
    ".rtf": "document",
    ".odt": "document",
    ".xls": "spreadsheet",
    ".xlsx": "spreadsheet",
    ".csv": "spreadsheet",
    ".ppt": "presentation",
    ".pptx": "presentation",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".gif": "image",
    ".webp": "image",
    ".bmp": "image",
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
    ".aac": "audio",
}


def _empty_counts() -> dict[str, int]:
    return {
        "total": 0,
        "retrievable": 0,
        "content_processing": 0,
        "tag_processing": 0,
        "failed": 0,
    }


def _document_type(file_name: Any) -> str:
    suffix = PurePath(str(file_name or "")).suffix.lower()
    if suffix in _VIDEO_EXTENSIONS:
        return "video"
    return _TYPE_BY_EXTENSION.get(suffix, "other")


async def _merged_runtime_tasks(kb: str) -> list[dict[str, Any]]:
    tasks_by_id: dict[str, dict[str, Any]] = {}
    offset = 0
    while True:
        uploads, total = await pg_list_uploads(
            kb_name=kb,
            limit=200,
            offset=offset,
            exclude_statuses=["completed", "processed", "deleted"],
        )
        for upload in uploads:
            if not isinstance(upload, dict):
                continue
            task_id = str(upload.get("task_id") or upload.get("id") or "")
            if not task_id:
                continue
            tasks_by_id[task_id] = {
                "id": task_id,
                "file": upload.get("filename") or upload.get("file_path") or "",
                "kb": kb,
                "status": upload.get("status") or "queued",
                "error_message": upload.get("error_message") or "",
                "started_at": upload.get("created_at") or "",
                "updated_at": upload.get("updated_at") or "",
            }
        offset += len(uploads)
        if not uploads or offset >= total:
            break
    for task in await get_all_tasks(kb_name=kb, limit=200):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or task.get("task_id") or "")
        if task_id:
            tasks_by_id[task_id] = {**task, "id": task_id}
    for raw_task_id, task in processing_tasks.items():
        if not isinstance(task, dict) or task.get("kb", task.get("kb_name", "")) != kb:
            continue
        task_id = str(task.get("id") or task.get("task_id") or raw_task_id)
        tasks_by_id[task_id] = {**tasks_by_id.get(task_id, {}), **task, "id": task_id}
    return list(tasks_by_id.values())


async def get_knowledge_inventory(kb: str) -> dict[str, Any]:
    """Return aggregate-only inventory using the document-list deduplication rules."""
    records = await load_document_summary_records(
        kb, runtime_tasks=await _merged_runtime_tasks(kb),
    )
    document_ids = [
        str(record["full_id"])
        for record in records
        if record.get("kind") == "document"
    ]
    try:
        tag_health_by_doc = await get_document_tag_health(kb, document_ids)
    except Exception:
        tag_health_by_doc = {}
    totals = _empty_counts()
    types: defaultdict[str, dict[str, int]] = defaultdict(_empty_counts)

    for record in records:
        runtime_task = record.get("runtime_task") or {}
        info = record.get("info") or {}
        is_runtime = record.get("kind") == "runtime"
        source = runtime_task if is_runtime else info
        file_type = _document_type(record.get("display_file") or source.get("file") or source.get("file_path"))
        counts = (totals, types[file_type])
        for bucket in counts:
            bucket["total"] += 1

        metadata = info.get("metadata") if isinstance(info.get("metadata"), dict) else {}
        raw_status = str(source.get("status") or "").lower()
        try:
            chunks_count = int(info.get("chunks_count") or 0)
        except (TypeError, ValueError):
            chunks_count = 0
        retrievable = (
            not is_runtime
            and metadata.get("content_ready") is True
            and chunks_count > 0
            and (raw_status in _RETRIEVABLE_STATUSES or raw_status == "failed")
        )
        if retrievable:
            for bucket in counts:
                bucket["retrievable"] += 1
            tag_status = str(tag_health_by_doc.get(str(record.get("full_id") or ""), {}).get("tag_status") or "").lower()
            if tag_status in _TAG_PROCESSING_STATUSES:
                for bucket in counts:
                    bucket["tag_processing"] += 1
        elif raw_status in _FAILED_STATUSES:
            for bucket in counts:
                bucket["failed"] += 1
        else:
            for bucket in counts:
                bucket["content_processing"] += 1

    return {
        "all": totals,
        "types": {file_type: counts for file_type, counts in sorted(types.items())},
    }
