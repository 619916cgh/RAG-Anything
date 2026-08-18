"""Deterministic OpenAI-compatible provider used only by the perf stack."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections.abc import AsyncIterator

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="RAG-Anything perf mock provider")
_COUNTS = {"models": 0, "text_embeddings": 0, "vision_embeddings": 0, "chat": 0}


def _int(name: str, default: int, minimum: int = 0) -> int:
    return max(minimum, int(os.getenv(name, str(default))))


def _failure(mode: str | None) -> None:
    if mode == "429":
        raise HTTPException(429, "injected rate limit")
    if mode == "500":
        raise HTTPException(500, "injected provider failure")


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str


class ChatRequest(BaseModel):
    model: str
    stream: bool = False
    messages: list[dict] | None = None
    max_tokens: int | None = None


class MultimodalEmbeddingRequest(BaseModel):
    input: list[dict]
    model: str
    dimensions: int | None = None


def _embedding(text: str, dimension: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).digest()
    return [((digest[index % len(digest)] / 255.0) * 2.0) - 1.0 for index in range(dimension)]


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/evidence")
async def evidence() -> dict[str, int]:
    """Expose aggregate test-only provider calls without request payloads."""
    return dict(_COUNTS)


@app.get("/v1/models")
async def models(x_perf_failure: str | None = Header(default=None)) -> dict:
    _COUNTS["models"] += 1
    _failure(x_perf_failure)
    return {"object": "list", "data": [{"id": "perf-mock", "object": "model"}]}


@app.post("/v1/embeddings")
async def embeddings(request: EmbeddingRequest, x_perf_failure: str | None = Header(default=None)) -> dict:
    _COUNTS["text_embeddings"] += 1
    _failure(x_perf_failure)
    values = [request.input] if isinstance(request.input, str) else request.input
    dimension = _int("PERF_EMBEDDING_DIM", 1536, 1)
    return {"object": "list", "data": [{"object": "embedding", "index": i, "embedding": _embedding(value, dimension)} for i, value in enumerate(values)], "model": request.model}


@app.post("/v1/embeddings/multimodal")
async def multimodal_embeddings(request: MultimodalEmbeddingRequest, x_perf_failure: str | None = Header(default=None)) -> dict:
    _COUNTS["vision_embeddings"] += 1
    _failure(x_perf_failure)
    dimension = request.dimensions or _int("PERF_EMBEDDING_DIM", 1536, 1)
    canonical = json.dumps(request.input, ensure_ascii=True, sort_keys=True)
    return {"object": "list", "data": [{"object": "embedding", "index": 0, "embedding": _embedding(canonical, dimension)}], "model": request.model}


async def _stream() -> AsyncIterator[str]:
    await asyncio.sleep(_int("PERF_MOCK_TTFT_MS", 100) / 1000)
    tokens = _int("PERF_MOCK_TOKEN_COUNT", 16, 1)
    interval = _int("PERF_MOCK_TOKEN_INTERVAL_MS", 20) / 1000
    for index in range(tokens):
        payload = {"id": "perf-mock", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": f"token-{index} "}, "finish_reason": None}]}
        yield f"data: {json.dumps(payload, ensure_ascii=True)}\n\n"
        await asyncio.sleep(interval)
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat(request: ChatRequest, x_perf_failure: str | None = Header(default=None)):
    _COUNTS["chat"] += 1
    _failure(x_perf_failure)
    if request.stream:
        return StreamingResponse(_stream(), media_type="text/event-stream")
    started = time.time()
    content = " ".join(f"token-{i}" for i in range(_int("PERF_MOCK_TOKEN_COUNT", 16, 1)))
    return JSONResponse({"id": "perf-mock", "object": "chat.completion", "created": int(started), "model": request.model, "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]})
