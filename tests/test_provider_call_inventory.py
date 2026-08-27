"""Contracts for the Qwen outbound-call inventory and DashScope rerank wrapper."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from raganything.services.provider_call_inventory import inventory_identifiers
from raganything.services.provider_governance import ProviderPriority


def test_qwen_provider_call_inventory_covers_required_entrypoints():
    required = {
        "llm_builder",
        "vlm_builder",
        "contextual_llm_vlm",
        "query_rewrite_and_citation_repair",
        "dashscope_rerank",
        "query_image_vlm",
        "agent_summary_and_fallback",
        "agentic",
        "legacy_kb_callbacks",
        "autorepair",
        "workflow_execution",
        "upload_background",
        "text_embedding",
    }
    assert required <= inventory_identifiers()


@pytest.mark.asyncio
async def test_dashscope_rerank_uses_governed_provider_operation(monkeypatch):
    from raganything.query import utils
    from raganything.services import vision_models

    calls = []

    async def governed(model, base_url, call, **kwargs):
        calls.append((model, base_url, kwargs))
        return await call()

    class Response:
        status = 200
        headers = {}

        async def json(self):
            return {"output": {"results": [{"index": 1, "relevance_score": 1.0}]}}

    class ResponseContext:
        async def __aenter__(self):
            return Response()

        async def __aexit__(self, *args):
            return False

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return ResponseContext()

    fake_aiohttp = SimpleNamespace(
        ClientSession=Session,
        ClientTimeout=lambda **kwargs: kwargs,
    )
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)
    monkeypatch.setattr(vision_models, "govern_openai_compatible_call", governed)

    ranked = await utils.rerank_chunks("question", ["first", "second"])

    assert ranked == [(1, "second"), (0, "first")]
    assert calls == [
        (
            "qwen3-rerank",
            "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
            {
                "capability": "rerank",
                "priority": ProviderPriority.QUERY,
                "allow_unprofiled": True,
            },
        )
    ]


@pytest.mark.asyncio
async def test_dashscope_rerank_does_not_log_provider_response_body(monkeypatch, caplog):
    from raganything.query import utils
    from raganything.services import vision_models

    async def governed(_model, _base_url, call, **_kwargs):
        return await call()

    class Response:
        status = 500
        headers = {}

        async def text(self):
            raise AssertionError("rerank must not read or log the provider body")

    class ResponseContext:
        async def __aenter__(self):
            return Response()

        async def __aexit__(self, *args):
            return False

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return ResponseContext()

    monkeypatch.setitem(
        sys.modules,
        "aiohttp",
        SimpleNamespace(ClientSession=Session, ClientTimeout=lambda **kwargs: kwargs),
    )
    monkeypatch.setattr(vision_models, "govern_openai_compatible_call", governed)

    assert await utils.rerank_chunks("private question", ["one", "two"]) == [
        (0, "one"),
        (1, "two"),
    ]
    assert "private question" not in caplog.text
