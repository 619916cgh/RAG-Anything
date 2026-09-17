"""Shared persisted-chunk reads for knowledge-base services and routes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


class PersistedChunkQueryError(RuntimeError):
    """Raised when the durable chunk fallback cannot be queried."""


def _normalise_chunk_row(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    chunk = dict(row)
    cache = chunk.get("llm_cache_list")
    if isinstance(cache, str):
        try:
            chunk["llm_cache_list"] = json.loads(cache)
        except json.JSONDecodeError:
            chunk["llm_cache_list"] = []
    return chunk


async def _query_document_chunk_page(
    execute,
    workspace: str,
    table_name: str,
    document_id: str,
    *,
    page: int,
    page_size: int,
    query: str = "",
    tag_id: int | None = None,
    kb_name: str | None = None,
    metadata_match_ids: list[str] | None = None,
) -> dict[str, Any]:
    params: list[Any] = [workspace, document_id]
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
            raise PersistedChunkQueryError(
                "kb_name is required for a tag-filtered chunk page"
            )
        params.append(tag_id)
        params.append(kb_name)
        predicates.append(
            "EXISTS (SELECT 1 FROM chunk_tag_assignments a "
            f"WHERE a.kb_name = ${len(params)} AND a.document_id = $2 "
            f"AND a.chunk_id = id AND a.tag_id = ${len(params) - 1})"
        )
    where = " AND ".join(predicates)
    filtered_sql = (
        "SELECT COUNT(*)::bigint AS total, "
        "COALESCE(SUM(tokens), 0)::bigint AS total_tokens "
        f"FROM {table_name} WHERE {where}"
    )
    document_sql = (
        "SELECT COUNT(*)::bigint AS total, "
        "COALESCE(SUM(tokens), 0)::bigint AS total_tokens "
        f"FROM {table_name} WHERE workspace = $1 AND full_doc_id = $2"
    )
    row_params = [*params, page_size, (page - 1) * page_size]
    rows_sql = (
        "SELECT id, content, tokens, chunk_order_index, file_path, "
        "full_doc_id, llm_cache_list "
        f"FROM {table_name} WHERE {where} ORDER BY chunk_order_index, id "
        f"LIMIT ${len(row_params) - 1} OFFSET ${len(row_params)}"
    )
    filtered_rows = await execute(filtered_sql, params)
    document_rows = await execute(document_sql, [workspace, document_id])
    rows = await execute(rows_sql, row_params)
    filtered = dict((filtered_rows or [{}])[0])
    document = dict((document_rows or [{}])[0])
    return {
        "records": [
            chunk for chunk in (_normalise_chunk_row(row) for row in rows or [])
            if chunk is not None
        ],
        "total": int(filtered.get("total") or 0),
        "total_tokens": int(filtered.get("total_tokens") or 0),
        "document_total": int(document.get("total") or 0),
        "document_total_tokens": int(document.get("total_tokens") or 0),
    }


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
        return [
            chunk for chunk in (_normalise_chunk_row(row) for row in rows or [])
            if chunk is not None
        ]
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
        return await _query_document_chunk_page(
            lambda sql, params: store.db.query(sql, params, multirows=True),
            store.workspace,
            table_name,
            document_id,
            page=page,
            page_size=page_size,
            query=query,
            tag_id=tag_id,
            kb_name=kb_name,
            metadata_match_ids=metadata_match_ids,
        )
    except Exception as exc:
        raise PersistedChunkQueryError(
            f"Unable to query paged persisted chunks for document {document_id}"
        ) from exc


async def query_document_chunk_page_direct(
    workspace: str,
    document_id: str,
    **kwargs,
) -> dict[str, Any] | None:
    """Read the native PostgreSQL chunk page without initializing LightRAG."""
    from raganything.services.pg_state_repo import get_pg_pool

    pool = get_pg_pool()
    try:
        async with pool.acquire() as conn:
            table_name = await conn.fetchval(
                "SELECT to_regclass('public.LIGHTRAG_DOC_CHUNKS')"
            )
            if not table_name:
                return None

            async def execute(sql: str, params: list[Any]):
                rows = await conn.fetch(sql, *params)
                return [dict(row) for row in rows]

            return await _query_document_chunk_page(
                execute,
                workspace,
                "LIGHTRAG_DOC_CHUNKS",
                document_id,
                **kwargs,
            )
    except Exception as exc:
        raise PersistedChunkQueryError(
            f"Unable to query direct persisted chunks for document {document_id}"
        ) from exc


async def get_chunk_record_direct(
    workspace: str,
    chunk_id: str,
) -> dict[str, Any] | None:
    """Read one persisted chunk without initializing a full LightRAG instance."""
    from raganything.services.pg_state_repo import get_pg_pool

    pool = get_pg_pool()
    try:
        async with pool.acquire() as conn:
            table_name = await conn.fetchval(
                "SELECT to_regclass('public.LIGHTRAG_DOC_CHUNKS')"
            )
            if not table_name:
                return None
            row = await conn.fetchrow(
                "SELECT id, content, tokens, chunk_order_index, file_path, "
                "full_doc_id, llm_cache_list "
                "FROM LIGHTRAG_DOC_CHUNKS WHERE workspace = $1 AND id = $2",
                workspace,
                chunk_id,
            )
            return _normalise_chunk_row(dict(row)) if row else None
    except Exception as exc:
        raise PersistedChunkQueryError(
            f"Unable to query direct persisted chunk {chunk_id}"
        ) from exc
