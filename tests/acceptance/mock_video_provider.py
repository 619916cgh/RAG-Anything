"""Deterministic OpenAI-compatible provider for isolated video acceptance."""
from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="RAG-Anything video acceptance provider")
TERMS = ("腐蚀", "漏液", "观察孔", "黑白", "5 Nm", "SVW2606")
SUMMARY = "蓄电池教学步骤：检查腐蚀和漏液，观察孔黑白状态，按 5 Nm 紧固端子，并核对 SVW2606。"


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str


class ChatRequest(BaseModel):
    model: str
    stream: bool = False
    messages: list[dict] | None = None


def _embedding(text: str, dimension: int = 1536) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).digest()
    values = [((digest[index % len(digest)] / 255.0) - 0.5) / 50 for index in range(dimension)]
    folded = text.casefold()
    for index, term in enumerate(TERMS):
        if term.casefold() in folded:
            values[index] = 1.0
    return values


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": "acceptance-mock", "object": "model"}]}


@app.post("/v1/embeddings")
async def embeddings(request: EmbeddingRequest):
    values = [request.input] if isinstance(request.input, str) else request.input
    return {"object": "list", "data": [
        {"object": "embedding", "index": index, "embedding": _embedding(value)}
        for index, value in enumerate(values)
    ], "model": request.model}


async def _stream() -> AsyncIterator[str]:
    payload = {"choices": [{"delta": {"content": SUMMARY}}]}
    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat(request: ChatRequest):
    if request.stream:
        return StreamingResponse(_stream(), media_type="text/event-stream")
    content = json.dumps({"detailed_description": SUMMARY}, ensure_ascii=False)
    return JSONResponse({"id": "acceptance-mock", "object": "chat.completion", "model": request.model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]})
