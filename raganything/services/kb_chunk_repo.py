"""Shared persisted-chunk reads for knowledge-base services and routes."""

from __future__ import annotations

import json
from typing import Any


class PersistedChunkQueryError(RuntimeError):
    """Raised when the durable chunk fallback cannot be queried."""


async def query_chunks_by_document_id(lightrag: Any, document_id: str) -> list[dict[str, Any]]:
    """Read a document's persisted chunks by ``full_doc_id`` from PostgreSQL.

    ``doc_status.chunks_list`` is a convenient index, but older and freshly
    persisted documents can temporarily have an empty list. The text-chunk
    store is the durable source of truth for that case.
    """
    try:
        from lightrag.kg.postgres_impl import PGKVStorage, namespace_to_table_name

        store = lightrag.text_chunks
        if not isinstance(store, PGKVStorage):
            return []
        table_name = namespace_to_table_name(store.namespace)
        sql = (
            f"SELECT id, content, tokens, chunk_order_index, file_path,"
            f" full_doc_id, llm_cache_list"
            f" FROM {table_name}"
            f" WHERE workspace = $1 AND full_doc_id = $2"
            f" ORDER BY chunk_order_index"
        )
        rows = await store.db.query(sql, [store.workspace, document_id], multirows=True)
        chunks: list[dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            chunk = dict(row)
            cache = chunk.get("llm_cache_list")
            if isinstance(cache, str):
                try:
                    chunk["llm_cache_list"] = json.loads(cache)
                except json.JSONDecodeError:
                    chunk["llm_cache_list"] = []
            chunks.append(chunk)
        return chunks
    except Exception as exc:
        raise PersistedChunkQueryError(
            f"Unable to query persisted chunks for document {document_id}"
        ) from exc


async def query_document_chunk_page(
    lightrag: Any,
    document_id: str,
    *,
    page: int,
    page_size: int,
    query: str = "",
    tag_id: int | None = None,
    kb_name: str | None = None,
    metadata_match_ids: list[str] | None = None,
) -> dict[str, Any] | None:
    """Return a native PostgreSQL page, or ``None`` for legacy stores."""
    try:
        from lightrag.kg.postgres_impl import PGKVStorage, namespace_to_table_name

        store = lightrag.text_chunks
        if not isinstance(store, PGKVStorage):
            return None
        table_name = namespace_to_table_name(store.namespace)
        params: list[Any] = [store.workspace, document_id]
        predicates = ["workspace = $1", "full_doc_id = $2"]
        if query or metadata_match_ids:
            clauses: list[str] = []
            if query:
                params.append(f"%{query}%")
                placeholder = len(params)
                clauses.append(
                    f"content ILIKE ${placeholder} OR id ILIKE ${placeholder}"
                )
            if metadata_match_ids:
                params.append(metadata_match_ids)
                clauses.append(f"id = ANY(${len(params)}::text[])")
            predicates.append("(" + " OR ".join(clauses) + ")")
        if tag_id is not None:
            if not kb_name:
                raise PersistedChunkQueryError("kb_name is required for a tag-filtered chunk page")
            params.append(tag_id)
            params.append(kb_name)
            predicates.append(
                "EXISTS (SELECT 1 FROM chunk_tag_assignments a "
                f"WHERE a.kb_name = ${len(params)} AND a.document_id = $2 "
                f"AND a.chunk_id = id AND a.tag_id = ${len(params) - 1})"
            )
        where = " AND ".join(predicates)
        filtered_sql = (
            f"SELECT COUNT(*)::bigint AS total, COALESCE(SUM(tokens), 0)::bigint AS total_tokens "
            f"FROM {table_name} WHERE {where}"
        )
        document_sql = (
            f"SELECT COUNT(*)::bigint AS total, COALESCE(SUM(tokens), 0)::bigint AS total_tokens "
            f"FROM {table_name} WHERE workspace = $1 AND full_doc_id = $2"
        )
        row_params = [*params, page_size, (page - 1) * page_size]
        rows_sql = (
            f"SELECT id, content, tokens, chunk_order_index, file_path, full_doc_id, llm_cache_list "
            f"FROM {table_name} WHERE {where} ORDER BY chunk_order_index, id "
            f"LIMIT ${len(row_params) - 1} OFFSET ${len(row_params)}"
        )
        filtered_rows = await store.db.query(filtered_sql, params, multirows=True)
        document_rows = await store.db.query(document_sql, [store.workspace, document_id], multirows=True)
        rows = await store.db.query(rows_sql, row_params, multirows=True)
        filtered = dict((filtered_rows or [{}])[0])
        document = dict((document_rows or [{}])[0])
        result_rows: list[dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            chunk = dict(row)
            if isinstance(chunk.get("llm_cache_list"), str):
                try:
                    chunk["llm_cache_list"] = json.loads(chunk["llm_cache_list"])
                except json.JSONDecodeError:
                    chunk["llm_cache_list"] = []
            result_rows.append(chunk)
        return {
            "records": result_rows,
            "total": int(filtered.get("total") or 0),
            "total_tokens": int(filtered.get("total_tokens") or 0),
            "document_total": int(document.get("total") or 0),
            "document_total_tokens": int(document.get("total_tokens") or 0),
        }
    except Exception as exc:
        raise PersistedChunkQueryError(
            f"Unable to query paged persisted chunks for document {document_id}"
        ) from exc
