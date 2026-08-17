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
from pathlib import Path
from typing import AsyncIterator

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
from raganything.utils.security import validate_query_input
from raganything.utils import display_document_name
from raganything.utils.media import is_supported_video_file


router = APIRouter(tags=["demo"])
_DEMO_MEDIA_TTL_SECONDS = min(max(int(os.getenv("DEMO_MEDIA_GRANT_TTL", "120")), 30), 300)
_DEMO_QUERY_TIMEOUT = max(1.0, float(os.getenv("DEMO_QUERY_TIMEOUT", "45")))
_SOURCE_MARKER = re.compile(r"\[来源\s*[:：]?\s*([^\]]+?)\]")


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
    media_id = payload.get("media_id")
    if not isinstance(media_id, str) or not media_id:
        return None
    expires_at = int(time.time()) + _DEMO_MEDIA_TTL_SECONDS
    return {
        "media_id": media_id,
        "caption": str(payload.get("caption") or ""),
        "mime": str(payload.get("mime") or ""),
        "url": f"/api/demo/{share.share_id}/media/{media_id}?grant={_media_grant(share.share_id, media_id, expires_at)}",
    }


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
    # Flush an immediate lifecycle event before potentially cold KB acquisition.
    yield _sse({"type": "accepted", "demo": True})
    try:
        # Keep the imported router module distinct from the fixed agent record.
        from raganything.routers import agent as agent_router

        runtime = agent_router._normalise_agent_config_values(dict(agent))
        runtime["system_prompt"] = agent_router._build_agent_system_prompt(agent)
        deadline = time.monotonic() + _DEMO_QUERY_TIMEOUT
        metadata = (await load_kb_meta()).get(share.kb_name, {})
        revision = str(metadata.get("updated_at") or metadata.get("created_at") or "unknown")
        scope = QueryExecutionScope(
            trace_id=f"demo:{share.share_id[:8]}", workspace=share.kb_name,
            corpus_revision=revision, permission_scope=f"demo:{share.share_id}",
            settings_fingerprint=f"demo-agent:{agent.get('id', '')}",
            llm_profile_fingerprint=f"demo-model:{runtime['llm_model']}", deadline_monotonic=deadline,
        )
        acquire_task = asyncio.create_task(
            acquire_query_kb(share.kb_name, corpus_revision=revision)
        )
        try:
            while not acquire_task.done():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    acquire_task.cancel()
                    await asyncio.gather(acquire_task, return_exceptions=True)
                    raise TimeoutError
                done, _ = await asyncio.wait({acquire_task}, timeout=min(5.0, remaining))
                if acquire_task not in done:
                    yield _sse({"type": "heartbeat", "demo": True})
            lease = acquire_task.result()
        finally:
            if not acquire_task.done():
                acquire_task.cancel()
                await asyncio.gather(acquire_task, return_exceptions=True)
        instance = lease.instance
        yield _sse({"type": "agent_info", "agent": agent.get("name", "演示助手"), "icon": agent.get("icon", ""), "demo": True})
        yield _sse({"type": "thinking", "content": "正在检索云端知识库..."})
        context = await await_before_deadline(
            instance.aquery(
                query, mode=runtime["query_mode"], only_need_context=True, vlm_enhanced=False,
                enable_rerank=runtime["enable_rerank"], chunk_top_k=runtime["chunk_top_k"],
                top_k=runtime["retrieval_top_k"], include_references=runtime["include_references"],
                query_execution_scope=scope,
            ), deadline,
        )
        if not isinstance(context, str) or not context.strip() or "[no-context]" in context:
            answer = "抱歉，知识库中暂无与您问题相关的数据，无法回答此问题。"
            yield _sse({"type": "token", "content": answer})
            yield _sse({"type": "done", "demo": True, "fallback": True})
            return

        prompt = PromptBuilder(max_total_tokens=int(os.getenv("MAX_TOKENS", "8192")))
        prompt.retrieval_context(context)
        prompt.user_query(query, "请基于检索内容作答；信息不足时明确说明。")
        final_prompt, _system = prompt.build()
        llm = agent_router._build_agent_llm(runtime)
        yield _sse({"type": "thinking", "content": "正在生成回答..."})
        response = await llm(final_prompt, system_prompt=runtime["system_prompt"], stream=True)
        answer = ""
        if isinstance(response, str):
            if await get_active_demo_share(share.share_id) is None:
                yield _sse({"type": "error", "content": "演示链接已失效"})
                return
            answer = response
            yield _sse({"type": "token", "content": response})
        else:
            async for token in response:
                if await get_active_demo_share(share.share_id) is None:
                    yield _sse({"type": "error", "content": "演示链接已失效"})
                    return
                answer += str(token)
                yield _sse({"type": "token", "content": str(token)})

        if await get_active_demo_share(share.share_id) is None:
            yield _sse({"type": "error", "content": "演示链接已失效"})
            return
        recalled, _backfill, _source, _timed_out = await agent_router._recall_controlled_media_with_budget(
            instance, query, share.kb_name, f"{context}\n{answer}",
        )
        media = [item for item in (_safe_demo_media_payload(share, value) for value in recalled) if item]
        yield _sse({"type": "done", "demo": True, "images": media, "sources": _safe_demo_sources(context)})
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
