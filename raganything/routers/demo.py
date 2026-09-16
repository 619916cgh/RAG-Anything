"""Anonymous, capability-scoped cloud knowledge-base demonstrations."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import mimetypes
import os
import re
import time
from math import isfinite
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from raganything.dependencies import get_current_user
from raganything.services.demo_shares import (
    DemoShare,
    acquire_demo_query,
    authenticate_demo_share,
    create_demo_share,
    get_active_demo_share,
    list_demo_shares,
    public_share_payload,
    release_demo_query,
    revoke_demo_share,
)
from raganything.services.kb_service import (
    _load_doc_status_json,
    acquire_query_kb,
    load_kb_meta,
)
from raganything.services.odl_media_delivery import resolve_catalog_media
from raganything.services.pg_agent_repo import pg_get_agent
from raganything.services.pg_agent_repo import pg_list_agents
from raganything.utils.kb_display_name import get_knowledge_base_display_name
from raganything.services.prompt_builder import PromptBuilder
from raganything.services.query_execution import QueryExecutionScope, await_before_deadline
from raganything.query.response_sanitizer import (
    ReferenceOutputFilter,
    strip_reference_markers,
)
from raganything.utils.security import validate_query_input
from raganything.utils import display_document_name
from raganything.utils.media import is_supported_video_file


router = APIRouter(tags=["demo"])
_DEMO_MEDIA_TTL_SECONDS = min(max(int(os.getenv("DEMO_MEDIA_GRANT_TTL", "120")), 30), 300)
_DEMO_QUERY_TIMEOUT = max(1.0, float(os.getenv("DEMO_QUERY_TIMEOUT", "45")))
_SOURCE_MARKER = re.compile(r"\[来源\s*[:：]?\s*([^\]]+?)\]")
_DEMO_MEDIA_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_DEMO_IDENTIFIER = re.compile(r"^[^\\/\r\n?#%]{1,512}$")
_LOCATOR_STATUSES = frozenset({"exact", "page", "document", "unavailable"})
_MODALITIES = frozenset({"text", "image", "video", "table", "audio"})
_LEGACY_STATUSES = frozenset({"legacy_unavailable"})
_MAX_SECTION_ITEMS = 32
_MAX_FRAME_REFS = 100
_MAX_VIDEO_SEGMENTS = 100
_MAX_EXCERPT_LENGTH = 8_000
_COORDINATE_TEXT_FIELDS = ("type", "name", "units", "unit", "kind", "origin")
_COORDINATE_NUMBER_FIELDS = (
    "width", "height", "page_width", "page_height", "image_width", "image_height",
)
_FRAME_TEXT_FIELDS = ("frame_id", "media_id", "element_id")
_FRAME_NUMBER_FIELDS = (
    "timestamp_ms", "index", "page", "page_idx", "x", "y", "width", "height",
)


class DemoShareCreate(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)


class DemoQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=10_000)


def _present_share(share: DemoShare, metadata: dict, agents_by_id: dict[str, dict]) -> dict:
    payload = public_share_payload(share)
    payload["kb_display_name"] = get_knowledge_base_display_name(
        metadata.get(share.kb_name),
        share.kb_name,
    )
    payload["agent_name"] = str(agents_by_id.get(share.agent_id, {}).get("name") or "智能体")
    return payload


def _require_super_admin(current_user: dict) -> dict:
    if not current_user.get("is_admin") or (current_user.get("role") or {}).get("name") != "super_admin":
        raise HTTPException(403, "需要超级管理员权限")
    return current_user


async def _authenticated_share(share_id: str, token: str | None) -> DemoShare:
    share = await authenticate_demo_share(share_id, token or "")
    if share is None:
        raise HTTPException(404, "demo unavailable")
    return share


async def _validated_share_agent(share: DemoShare) -> tuple[dict, dict]:
    agent = await pg_get_agent(share.agent_id)
    metadata = await load_kb_meta()
    if not agent or str(agent.get("kb_name") or "") != share.kb_name or share.kb_name not in metadata:
        raise HTTPException(404, "demo unavailable")
    return agent, metadata[share.kb_name]


def _media_secret() -> bytes:
    raw = os.getenv("DEMO_MEDIA_GRANT_SECRET") or os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY")
    if not raw:
        raise RuntimeError("demo media grant secret is unavailable")
    return raw.encode("utf-8")


def _media_grant(share_id: str, media_id: str, expires_at: int) -> str:
    message = f"demo-media:{share_id}:{media_id}:{expires_at}".encode("utf-8")
    signature = hmac.new(_media_secret(), message, hashlib.sha256).hexdigest()
    return f"{expires_at}.{signature}"


def _verify_media_grant(share_id: str, media_id: str, grant: str) -> bool:
    try:
        expires_raw, signature = grant.split(".", 1)
        expires_at = int(expires_raw)
    except (AttributeError, TypeError, ValueError):
        return False
    if expires_at < int(time.time()):
        return False
    try:
        expected = _media_grant(share_id, media_id, expires_at)
    except RuntimeError:
        return False
    return hmac.compare_digest(grant, expected)


def _safe_demo_media_payload(share: DemoShare, payload: dict) -> dict | None:
    media_id = _safe_demo_media_id(payload.get("media_id"))
    if media_id is None:
        return None
    expires_at = int(time.time()) + _DEMO_MEDIA_TTL_SECONDS
    return {
        "media_id": media_id,
        "caption": str(payload.get("caption") or ""),
        "mime": str(payload.get("mime") or ""),
        "url": (
            f"/api/demo/{share.share_id}/media/{quote(media_id, safe='')}?"
            f"grant={_media_grant(share.share_id, media_id, expires_at)}"
        ),
    }


def _safe_text(value: object, *, max_length: int = 512) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:max_length] if text else None


def _safe_identifier(value: object) -> str | None:
    text = _safe_text(value)
    return text if text and _DEMO_IDENTIFIER.fullmatch(text) else None


def _safe_number(
    value: object, *, minimum: float | None = None, integer: bool = False,
) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if (
        not isfinite(number)
        or (minimum is not None and number < minimum)
        or (integer and not number.is_integer())
    ):
        return None
    return int(number) if integer else value


def _safe_demo_media_id(value: object) -> str | None:
    text = _safe_text(value)
    return text if text and _DEMO_MEDIA_ID.fullmatch(text) else None


def _safe_bbox(value: object) -> dict[str, int | float] | None:
    if not isinstance(value, dict):
        return None
    bbox: dict[str, int | float] = {}
    for field in ("x", "y", "width", "height"):
        number = _safe_number(
            value.get(field), minimum=0 if field in {"width", "height"} else None
        )
        if number is None:
            return None
        bbox[field] = number
    return bbox


def _safe_coordinate_system(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    safe: dict = {}
    for field in _COORDINATE_TEXT_FIELDS:
        if (text := _safe_identifier(value.get(field))) is not None:
            safe[field] = text
    for field in _COORDINATE_NUMBER_FIELDS:
        if (number := _safe_number(value.get(field), minimum=0)) is not None:
            safe[field] = number
    order = value.get("order")
    if isinstance(order, list):
        safe_order = [
            text for item in order[:8]
            if (text := _safe_identifier(item)) is not None
        ]
        if safe_order:
            safe["order"] = safe_order
    return safe or None


def _safe_frame_refs(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    refs: list[dict] = []
    for item in value[:_MAX_FRAME_REFS]:
        if not isinstance(item, dict):
            continue
        safe: dict = {}
        for field in _FRAME_TEXT_FIELDS:
            text = _safe_demo_media_id(item.get(field)) if field == "media_id" else _safe_identifier(item.get(field))
            if text is not None:
                safe[field] = text
        for field in _FRAME_NUMBER_FIELDS:
            if (number := _safe_number(item.get(field), minimum=0)) is not None:
                safe[field] = number
        if safe:
            refs.append(safe)
    return refs


def _safe_video_segment(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    safe: dict = {}
    if (media_id := _safe_demo_media_id(value.get("media_id"))) is not None:
        safe["media_id"] = media_id
    if (segment_id := _safe_identifier(value.get("segment_id"))) is not None:
        safe["segment_id"] = segment_id
    for field in ("start_ms", "end_ms"):
        if (number := _safe_number(value.get(field), minimum=0, integer=True)) is not None:
            safe[field] = number
    frame_refs = _safe_frame_refs(value.get("frame_refs"))
    if frame_refs:
        safe["frame_refs"] = frame_refs
    return safe or None


def _safe_image(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    safe: dict = {}
    for field in ("element_id", "figure_label"):
        if (text := _safe_identifier(value.get(field))) is not None:
            safe[field] = text
    if (media_id := _safe_demo_media_id(value.get("media_id"))) is not None:
        safe["media_id"] = media_id
    if (bbox := _safe_bbox(value.get("bbox"))) is not None:
        safe["bbox"] = bbox
    if (coordinate_system := _safe_coordinate_system(value.get("bbox_coordinate_system"))) is not None:
        safe["bbox_coordinate_system"] = coordinate_system
    return safe or None


def _has_invalid_media_id(value: object) -> bool:
    if not isinstance(value, dict) or "media_id" not in value:
        return False
    raw = value.get("media_id")
    return raw not in (None, "") and _safe_demo_media_id(raw) is None


def _safe_demo_citation(share: DemoShare, citation: dict) -> dict | None:
    """Build a deep allowlisted DTO and replace private media grants."""
    if not isinstance(citation, dict):
        return None
    safe: dict = {}
    for field in ("citation_id", "document_id", "chunk_id"):
        if (identifier := _safe_identifier(citation.get(field))) is not None:
            safe[field] = identifier
    if (document_name := _safe_text(citation.get("document_name"))) is not None:
        safe["document_name"] = display_document_name(document_name)
    if (
        excerpt := _safe_text(
            citation.get("excerpt"), max_length=_MAX_EXCERPT_LENGTH
        )
    ) is not None:
        from raganything.services.provenance import _redact_excerpt

        if (redacted_excerpt := _redact_excerpt(excerpt)):
            safe["excerpt"] = redacted_excerpt
    for field, allowed in (
        ("modality", _MODALITIES),
        ("locator_status", _LOCATOR_STATUSES),
        ("legacy_status", _LEGACY_STATUSES),
    ):
        value = str(citation.get(field) or "").strip().lower()
        if value in allowed:
            safe[field] = value
    if (index := _safe_number(citation.get("index"), minimum=1, integer=True)) is not None:
        safe["index"] = index
    if (page := _safe_number(citation.get("page"), minimum=1, integer=True)) is not None:
        safe["page"] = page
    if isinstance(citation.get("section_path"), list):
        safe["section_path"] = [
            text for item in citation["section_path"][:_MAX_SECTION_ITEMS]
            if (text := _safe_text(item)) is not None
        ]

    top_media_id = _safe_demo_media_id(citation.get("media_id"))
    image = _safe_image(citation.get("image"))
    if image is not None:
        safe["image"] = image
    segment = _safe_video_segment(citation.get("video_segment"))
    if segment is not None:
        safe["video_segment"] = segment
    raw_segments = citation.get("video_segments")
    if isinstance(raw_segments, list):
        segments = [
            safe_segment for item in raw_segments[:_MAX_VIDEO_SEGMENTS]
            if (safe_segment := _safe_video_segment(item)) is not None
        ]
        if segments:
            safe["video_segments"] = segments

    invalid_media_id = any((
        _has_invalid_media_id(citation),
        _has_invalid_media_id(citation.get("image")),
        _has_invalid_media_id(citation.get("video_segment")),
        any(_has_invalid_media_id(item) for item in raw_segments)
        if isinstance(raw_segments, list) else False,
    ))
    media_ids = {
        media_id for media_id in (
            top_media_id,
            image.get("media_id") if image else None,
            segment.get("media_id") if segment else None,
            *(item.get("media_id") for item in safe.get("video_segments", [])),
        ) if media_id
    }
    if not invalid_media_id and len(media_ids) == 1:
        media_id = next(iter(media_ids))
        safe["media_id"] = media_id
        expires_at = int(time.time()) + _DEMO_MEDIA_TTL_SECONDS
        media_url = (
            f"/api/demo/{share.share_id}/media/{quote(media_id, safe='')}?"
            f"grant={_media_grant(share.share_id, media_id, expires_at)}"
        )
        safe["media_url"] = media_url
        if image is not None:
            safe["image"]["media_url"] = media_url
    return safe or None


def _safe_demo_sources(context: object) -> list[dict[str, str]]:
    """Expose deduplicated display names only, never retrieval metadata or paths."""
    if not isinstance(context, str):
        return []
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _SOURCE_MARKER.finditer(context):
        name = display_document_name(match.group(1).strip())
        if not name or name in seen:
            continue
        seen.add(name)
        sources.append({"name": name})
        if len(sources) == 20:
            break
    return sources


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _demo_events(share: DemoShare, agent: dict, query: str, request: Request) -> AsyncIterator[str]:
    """Run a fixed-agent RAG query without conversation or query-history writes."""
    lease = None
    try:
        # Keep the imported router module distinct from the fixed agent record.
        from raganything.routers import agent as agent_router

        runtime = agent_router._normalise_agent_config_values(dict(agent))
        include_references = runtime["include_references"]
        agent_mode = agent_router._normalise_agent_mode(
            runtime.get("agent_mode")
        )
        runtime["agent_mode"] = agent_mode
        runtime["system_prompt"] = agent_router._build_agent_system_prompt(
            agent,
            include_references=include_references,
        )
        deadline = time.monotonic() + _DEMO_QUERY_TIMEOUT
        metadata = (await load_kb_meta()).get(share.kb_name, {})
        revision = str(metadata.get("updated_at") or metadata.get("created_at") or "unknown")
        scope = QueryExecutionScope(
            trace_id=f"demo:{share.share_id[:8]}", workspace=share.kb_name,
            corpus_revision=revision, permission_scope=f"demo:{share.share_id}",
            settings_fingerprint=f"demo-agent:{agent.get('id', '')}",
            llm_profile_fingerprint=f"demo-model:{runtime['llm_model']}", deadline_monotonic=deadline,
            provenance_sink=[],
        )
        lease = await await_before_deadline(
            acquire_query_kb(share.kb_name, corpus_revision=revision), deadline, cancel_on_timeout=False,
        )
        instance = lease.instance
        yield _sse({"type": "agent_info", "agent": agent.get("name", "演示助手"), "icon": agent.get("icon", ""), "demo": True})
        yield _sse({"type": "thinking", "content": "正在处理问题..."})

        context = ""
        answer = ""
        answer_filter = ReferenceOutputFilter(enabled=not include_references)

        if agent_mode == "react":
            from raganything.agentic_rag import AgenticRAG, SearchTool

            llm = agent_router._build_agent_llm(runtime)

            async def bounded_llm(prompt, **kwargs):
                return await await_before_deadline(
                    llm(prompt, **kwargs),
                    deadline,
                )

            agentic = AgenticRAG(
                llm_func=bounded_llm,
                max_steps=int(os.getenv("AGENT_MAX_STEPS", "5")),
                mode="react",
                max_response_tokens=runtime["max_response_tokens"],
                system_prompt_override=runtime["system_prompt"],
                include_references=include_references,
            )
            agentic.register_tool(SearchTool(
                instance,
                query_mode=runtime["query_mode"],
                top_k=runtime["retrieval_top_k"],
                chunk_top_k=runtime["chunk_top_k"],
                enable_rerank=runtime["enable_rerank"],
                include_references=include_references,
                query_execution_scope=scope,
            ))
            context_parts: list[str] = []
            last_event = None
            async for event in agentic.run_stream(query):
                last_event = event
                if event.type == "thinking" and event.observation:
                    context_parts.append(event.observation)
                elif event.type == "token":
                    visible = answer_filter.feed(event.content or "")
                    if visible:
                        answer += visible
                        yield _sse({"type": "token", "content": visible})
                elif event.type == "done":
                    if (
                        include_references
                        and event.answer
                        and len(event.answer) > len(answer)
                    ):
                        answer = event.answer
                    break
            visible_tail = answer_filter.finish()
            if visible_tail:
                answer += visible_tail
                yield _sse({"type": "token", "content": visible_tail})
            if (
                not include_references
                and not answer
                and last_event is not None
                and last_event.answer
            ):
                answer = strip_reference_markers(last_event.answer)
                if answer:
                    yield _sse({"type": "token", "content": answer})
            context = "\n".join(context_parts)
        else:
            context = await await_before_deadline(
                instance.aquery(
                    query, mode=runtime["query_mode"], only_need_context=True, vlm_enhanced=False,
                    enable_rerank=runtime["enable_rerank"], chunk_top_k=runtime["chunk_top_k"],
                    top_k=runtime["retrieval_top_k"], include_references=include_references,
                    query_execution_scope=scope,
                ), deadline,
            )

        if agent_mode != "react" and (
            not isinstance(context, str)
            or not context.strip()
            or "[no-context]" in context
        ):
            answer = "抱歉，知识库中暂无与您问题相关的数据，无法回答此问题。"
            yield _sse({"type": "token", "content": answer})
            yield _sse({
                "type": "done", "demo": True, "fallback": True,
                "citations": [], "images": [], "sources": [],
            })
            return

        llm = agent_router._build_agent_llm(runtime)
        if agent_mode == "cot":
            from raganything.agentic_rag import AgenticRAG

            async def bounded_llm(prompt, **kwargs):
                return await await_before_deadline(
                    llm(prompt, **kwargs),
                    deadline,
                )

            agentic = AgenticRAG(
                llm_func=bounded_llm,
                max_steps=int(os.getenv("AGENT_MAX_STEPS", "5")),
                mode="cot",
                max_response_tokens=runtime["max_response_tokens"],
                system_prompt_override=runtime["system_prompt"],
                include_references=include_references,
            )
            result = await await_before_deadline(
                agentic.run_with_context(query, context),
                deadline,
            )
            answer = (
                result.answer
                if include_references
                else strip_reference_markers(result.answer)
            )
            if answer:
                yield _sse({"type": "token", "content": answer})
        elif agent_mode == "none":
            yield _sse({"type": "thinking", "content": "正在生成回答..."})
            citation_instruction = (
                "请基于检索内容作答；引用时必须原样复用对应的 `[来源 N]` 编号，"
                "不得改号或编造；信息不足时明确说明。"
                if include_references
                else "请基于检索内容作答，不要输出来源标记、参考来源块或引用列表；"
                "信息不足时明确说明。"
            )
            prompt = PromptBuilder(max_total_tokens=int(os.getenv("MAX_TOKENS", "8192")))
            prompt.retrieval_context(context)
            prompt.user_query(query, citation_instruction)
            final_prompt, _system = prompt.build()
            response = await await_before_deadline(
                llm(
                    final_prompt,
                    system_prompt=runtime["system_prompt"],
                    stream=True,
                ),
                deadline,
            )
            if isinstance(response, str):
                if await get_active_demo_share(share.share_id) is None:
                    yield _sse({"type": "error", "content": "演示链接已失效"})
                    return
                answer = answer_filter.feed(response) + answer_filter.finish()
                if answer:
                    yield _sse({"type": "token", "content": answer})
            else:
                async for token in response:
                    if await get_active_demo_share(share.share_id) is None:
                        yield _sse({"type": "error", "content": "演示链接已失效"})
                        return
                    visible = answer_filter.feed(str(token))
                    if visible:
                        answer += visible
                        yield _sse({"type": "token", "content": visible})
                visible_tail = answer_filter.finish()
                if visible_tail:
                    answer += visible_tail
                    yield _sse({"type": "token", "content": visible_tail})

        if await get_active_demo_share(share.share_id) is None:
            yield _sse({"type": "error", "content": "演示链接已失效"})
            return
        media = []
        if include_references:
            recalled, _backfill, _source, _timed_out = await agent_router._recall_controlled_media_with_budget(
                instance, query, share.kb_name, f"{context}\n{answer}",
            )
            media = [
                item for item in (
                    _safe_demo_media_payload(share, value) for value in recalled
                ) if item
            ]
        citations = []
        sources = []
        if include_references:
            citations = await agent_router._provenance_citations_from_scope(
                scope, share.kb_name, answer
            )
            citations = [
                safe for citation in citations
                if (safe := _safe_demo_citation(share, citation)) is not None
            ]
            seen_sources = set()
            for citation in citations:
                name = display_document_name(citation.get("document_name"))
                if name and name not in seen_sources:
                    seen_sources.add(name)
                    sources.append({"name": name})
            if not sources:
                sources = _safe_demo_sources(context)
        yield _sse({
            "type": "done",
            "demo": True,
            "images": media,
            "sources": sources,
            "citations": citations,
        })
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        yield _sse({"type": "error", "content": "云端知识库响应超时，请稍后重试。"})
    except Exception:
        yield _sse({"type": "error", "content": "问答暂时不可用，请稍后重试。"})
    finally:
        if lease is not None:
            await lease.release()
        await release_demo_query(share.share_id)


@router.get("/demo/shares")
async def list_shares(current_user: dict = Depends(get_current_user)):
    _require_super_admin(current_user)
    shares = await list_demo_shares()
    metadata = await load_kb_meta()
    agents = await pg_list_agents(user_id=current_user["id"], is_admin=True)
    agents_by_id = {str(agent.get("id")): agent for agent in agents}
    return {"shares": [_present_share(share, metadata, agents_by_id) for share in shares]}


@router.post("/demo/shares")
async def create_share(payload: DemoShareCreate, current_user: dict = Depends(get_current_user)):
    _require_super_admin(current_user)
    agent = await pg_get_agent(payload.agent_id)
    if not agent or not str(agent.get("kb_name") or ""):
        raise HTTPException(422, "智能体必须绑定有效知识库")
    metadata = await load_kb_meta()
    kb_name = str(agent["kb_name"])
    if kb_name not in metadata:
        raise HTTPException(422, "智能体绑定的知识库不存在")
    share, token = await create_demo_share(payload.agent_id, kb_name, int(current_user["id"]))
    return {
        "share": _present_share(share, metadata, {str(agent.get("id")): agent}),
        "token": token,
    }


@router.delete("/demo/shares/{share_id}")
async def revoke_share(share_id: str, current_user: dict = Depends(get_current_user)):
    _require_super_admin(current_user)
    if not await revoke_demo_share(share_id):
        raise HTTPException(404, "演示链接不存在")
    return {"status": "revoked"}


@router.get("/demo/{share_id}/bootstrap")
async def demo_bootstrap(share_id: str, x_demo_token: str | None = Header(default=None)):
    share = await _authenticated_share(share_id, x_demo_token)
    agent, kb_meta = await _validated_share_agent(share)
    extra = kb_meta.get("extra") if isinstance(kb_meta, dict) else {}
    ingestion = (extra or {}).get("ingestion_defaults") if isinstance(extra, dict) else {}
    ingestion = ingestion if isinstance(ingestion, dict) else {}
    return {
        "agent": {"name": agent.get("name", "演示助手"), "icon": agent.get("icon", ""), "welcome_message": agent.get("welcome_message", "")},
        "knowledge_base": {"name": get_knowledge_base_display_name(kb_meta, share.kb_name), "parser": ingestion.get("parser") or "系统默认", "chunking_strategy": ingestion.get("chunking_strategy") or "系统默认"},
    }


@router.post("/demo/{share_id}/query/stream")
async def demo_query_stream(share_id: str, payload: DemoQueryRequest, request: Request, x_demo_token: str | None = Header(default=None)):
    share = await _authenticated_share(share_id, x_demo_token)
    agent, _kb_meta = await _validated_share_agent(share)
    try:
        validate_query_input(payload.query, user_id=f"demo:{share.share_id}")
    except Exception as exc:
        raise HTTPException(422, "问题无法处理") from exc
    if not await acquire_demo_query(share):
        raise HTTPException(429, "演示请求过于频繁，请稍后重试。", headers={"Retry-After": "60"})
    return StreamingResponse(
        _demo_events(share, agent, payload.query.strip(), request), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


def _controlled_video_path(server_path: object) -> Path | None:
    if not isinstance(server_path, str) or not server_path:
        return None
    try:
        candidate = Path(server_path)
        resolved = candidate.resolve(strict=True)
        upload_root = (Path.cwd() / "uploads").resolve(strict=True)
        if candidate.is_symlink() or not resolved.is_file() or not is_supported_video_file(resolved):
            return None
        resolved.relative_to(upload_root)
        return resolved
    except (OSError, RuntimeError, ValueError):
        return None


@router.get("/demo/{share_id}/media/{media_id}")
async def demo_media(share_id: str, media_id: str, grant: str):
    if not _verify_media_grant(share_id, media_id, grant):
        raise HTTPException(404, "media unavailable")
    share = await get_active_demo_share(share_id)
    if share is None:
        raise HTTPException(404, "media unavailable")
    statuses = await _load_doc_status_json(share.kb_name) or {}
    matches = []
    for status in statuses.values():
        metadata = status.get("metadata") if isinstance(status, dict) else None
        media = resolve_catalog_media(
            metadata.get("odl_media_catalog") if isinstance(metadata, dict) else None,
            kb_name=share.kb_name, media_id=media_id,
        )
        if media is not None:
            matches.append(media)
    if len(matches) == 1:
        media = matches[0]
        return FileResponse(str(media.path), media_type=media.mime, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
    if matches:
        raise HTTPException(404, "media unavailable")
    from raganything.services.video_segments import get_video_asset
    asset = await get_video_asset(share.kb_name, media_id)
    path = _controlled_video_path(asset.get("server_path") if asset else None)
    if path is None:
        raise HTTPException(404, "media unavailable")
    media_type = mimetypes.guess_type(path.name)[0] or "video/mp4"
    return FileResponse(str(path), media_type=media_type, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
