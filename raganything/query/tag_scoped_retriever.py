"""Strict retrieval restricted to the chunks assigned to one KB tag."""

from __future__ import annotations

import asyncio
import math
import os
from dataclasses import dataclass
from typing import Any

import jieba

from raganything.services.kb_tag_repo import get_tag_assignments
from raganything.services.query_execution import await_before_deadline
from raganything.utils import display_document_name


@dataclass(frozen=True)
class TagScope:
    tag_id: int
    tag_name: str
    chunk_ids: tuple[str, ...]

    @property
    def label(self) -> str:
        return f"标签范围：{self.tag_name}"


async def resolve_tag_scope(kb_name: str, tag_id: int) -> TagScope | None:
    tag, assignments = await get_tag_assignments(kb_name, tag_id)
    if not tag:
        return None
    chunk_ids = tuple(dict.fromkeys(item["chunk_id"] for item in assignments if item.get("chunk_id")))
    return TagScope(tag_id=int(tag["id"]), tag_name=tag["name"], chunk_ids=chunk_ids)


async def retrieve_tag_scoped_context(
    instance: Any,
    scope: TagScope,
    query: str,
    *,
    top_k: int = 20,
    retrieval_top_k: int | None = None,
    enable_rerank: bool = False,
    max_total_tokens: int = 8000,
    deadline_monotonic: float | None = None,
    query_execution_scope: Any = None,
    include_references: bool = True,
) -> str:
    """Retrieve tagged context without exceeding the request-wide deadline."""
    try:
        return await await_before_deadline(
            _retrieve_tag_scoped_context_unbounded(
                instance,
                scope,
                query,
                top_k=top_k,
                retrieval_top_k=retrieval_top_k,
                enable_rerank=enable_rerank,
                max_total_tokens=max_total_tokens,
                deadline_monotonic=deadline_monotonic,
                query_execution_scope=query_execution_scope,
                include_references=include_references,
            ),
            deadline_monotonic,
        )
    except TimeoutError:
        return ""


async def _retrieve_tag_scoped_context_unbounded(
    instance: Any,
    scope: TagScope,
    query: str,
    *,
    top_k: int = 20,
    retrieval_top_k: int | None = None,
    enable_rerank: bool = False,
    max_total_tokens: int = 8000,
    deadline_monotonic: float | None = None,
    query_execution_scope: Any = None,
    include_references: bool = True,
) -> str:
    """Rank only tagged chunks, then build citation-friendly RAG context.

    LightRAG's vector storage does not expose a stable metadata predicate across
    all configured backends. Fetching the tag-owned candidate set first makes
    the scope strict; lexical ranking is always available, and semantic rerank
    improves ordering when the configured embedding function is available.
    """
    if not scope.chunk_ids:
        return ""

    records = await instance.lightrag.text_chunks.get_by_ids(list(scope.chunk_ids))
    chunks = [dict(value) for value in (records or []) if isinstance(value, dict) and value.get("content")]
    if not chunks:
        return ""

    final_limit = max(1, min(int(top_k or 20), 100))
    candidate_limit = (
        final_limit
        if retrieval_top_k is None
        else max(final_limit, min(int(retrieval_top_k), 200))
    )
    ranked = await _rank_chunks(
        instance,
        chunks,
        query,
        top_k=final_limit,
        retrieval_top_k=candidate_limit,
        enable_rerank=enable_rerank,
        deadline_monotonic=deadline_monotonic,
    )
    token_budget = max(1000, int(max_total_tokens or 8000))
    used_tokens = 0
    sections = [f"[检索范围仅限标签：{scope.tag_name}]" ]
    selected = []
    for chunk in ranked:
        content = str(chunk.get("content") or "").strip()
        if not content:
            continue
        tokens = int(chunk.get("tokens") or max(1, len(content) // 2))
        if len(sections) > 1 and used_tokens + tokens > token_budget:
            break
        selected.append(chunk)
        used_tokens += tokens

    if not selected:
        return ""

    from raganything.query.pipeline import (
        _format_provenance_context,
        _prepare_provenance_references,
        _register_provenance_references,
        _scope_provenance_sink,
    )

    if _scope_provenance_sink(query_execution_scope) is not None:
        references = await _prepare_provenance_references(instance, selected)
        registered = _register_provenance_references(
            query_execution_scope, references
        )
        sections.append(
            _format_provenance_context(
                registered,
                include_references=include_references,
            )
        )
        return "\n\n".join(sections)

    for chunk in selected:
        content = str(chunk.get("content") or "").strip()
        filename = display_document_name(chunk.get("file_path"), default="未命名文档")
        order = chunk.get("chunk_order_index")
        position = f"，切块 {int(order) + 1}" if isinstance(order, int) or str(order).isdigit() else ""
        if include_references:
            sections.append(f"[来源：{filename}{position}]\n{content}")
        else:
            sections.append(content)
    return "\n\n".join(sections) if len(sections) > 1 else ""


async def _rank_chunks(
    instance: Any,
    chunks: list[dict[str, Any]],
    query: str,
    *,
    top_k: int,
    retrieval_top_k: int,
    enable_rerank: bool,
    deadline_monotonic: float | None,
) -> list[dict[str, Any]]:
    lexical_scores = _lexical_scores(query, chunks)
    ranked_indices = sorted(range(len(chunks)), key=lambda index: lexical_scores[index], reverse=True)
    candidate_limit = min(len(chunks), max(top_k, retrieval_top_k, 1))
    candidate_indices = ranked_indices[:candidate_limit]
    if not enable_rerank:
        return [chunks[index] for index in candidate_indices[:top_k]]

    semantic_scores = await _semantic_scores(instance, query, [chunks[index] for index in candidate_indices])

    lexical_max = max((lexical_scores[index] for index in candidate_indices), default=0.0)
    combined: list[tuple[float, int]] = []
    for position, index in enumerate(candidate_indices):
        lexical = lexical_scores[index] / lexical_max if lexical_max > 0 else 0.0
        semantic = semantic_scores[position] if semantic_scores else 0.0
        # Semantic scores are cosine similarities in [-1, 1]. Map to [0, 1].
        semantic = (semantic + 1.0) / 2.0 if semantic_scores else 0.0
        score = (0.65 * semantic + 0.35 * lexical) if semantic_scores else lexical
        combined.append((score, index))
    combined.sort(key=lambda value: value[0], reverse=True)
    locally_ranked = [chunks[index] for _, index in combined]

    rerank_api_key = os.getenv(
        "LLM_BINDING_API_KEY",
        os.getenv("RERANK_BINDING_API_KEY", ""),
    ).strip()
    if not rerank_api_key:
        return locally_ranked[:top_k]

    try:
        from raganything.query.utils import rerank_chunks

        ranked = await await_before_deadline(
            rerank_chunks(
                query,
                [str(chunk.get("content") or "") for chunk in locally_ranked],
                api_key=rerank_api_key,
                model=os.getenv("RERANK_MODEL", "qwen3-rerank"),
                top_n=top_k,
            ),
            deadline_monotonic,
        )
    except Exception:
        return locally_ranked[:top_k]

    reranked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, _content in ranked:
        if isinstance(index, int) and 0 <= index < len(locally_ranked):
            chunk = locally_ranked[index]
            chunk_id = str(chunk.get("chunk_id") or id(chunk))
            if chunk_id not in seen:
                seen.add(chunk_id)
                reranked.append(chunk)
    for chunk in locally_ranked:
        chunk_id = str(chunk.get("chunk_id") or id(chunk))
        if chunk_id not in seen:
            seen.add(chunk_id)
            reranked.append(chunk)
    return reranked[:top_k]


def _lexical_scores(query: str, chunks: list[dict[str, Any]]) -> list[float]:
    query_terms = [item for item in jieba.cut(query or "") if item.strip()]
    if not query_terms:
        return [0.0] * len(chunks)
    try:
        from rank_bm25 import BM25Okapi

        corpus = [list(jieba.cut(str(chunk.get("content") or ""))) for chunk in chunks]
        return [float(value) for value in BM25Okapi(corpus).get_scores(query_terms)]
    except Exception:
        normalized = " ".join(query_terms).casefold()
        return [float(str(chunk.get("content") or "").casefold().count(normalized)) for chunk in chunks]


async def _semantic_scores(instance: Any, query: str, chunks: list[dict[str, Any]]) -> list[float]:
    embedding = getattr(instance, "embedding_func", None) or getattr(instance.lightrag, "embedding_func", None)
    embedding = getattr(embedding, "func", embedding)
    if embedding is None or not chunks:
        return []
    try:
        vectors = await embedding([query, *[str(chunk.get("content") or "") for chunk in chunks]])
        values = list(vectors)
        if len(values) != len(chunks) + 1:
            return []
        query_vector = _as_vector(values[0])
        return [_cosine(query_vector, _as_vector(value)) for value in values[1:]]
    except Exception:
        return []


def _as_vector(value: Any) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    return [float(item) for item in value]


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0
