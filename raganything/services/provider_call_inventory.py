"""Auditable inventory of server-side Qwen-capable outbound call entry points.

This is intentionally a static, secret-free contract rather than runtime
telemetry.  It gives review and regression tests a single place to identify
where a newly added direct model call must be governed.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderCallEntry:
    identifier: str
    location: str
    governance_boundary: str


QWEN_PROVIDER_CALL_INVENTORY: tuple[ProviderCallEntry, ...] = (
    ProviderCallEntry(
        "llm_builder",
        "raganything.services.vision_models.build_llm_callable",
        "profile builder -> ProviderGovernor",
    ),
    ProviderCallEntry(
        "vlm_builder",
        "raganything.services.vision_models.build_vlm_callable",
        "profile builder -> ProviderGovernor",
    ),
    ProviderCallEntry(
        "contextual_llm_vlm",
        "raganything.services.vision_models.build_contextual_*_callable",
        "contextual proxy -> governed profile builder",
    ),
    ProviderCallEntry(
        "query_rewrite_and_citation_repair",
        "raganything.query.utils.rewrite_query; raganything.query.pipeline._ensure_citations",
        "instance llm_model_func -> governed profile builder",
    ),
    ProviderCallEntry(
        "dashscope_rerank",
        "raganything.query.utils.rerank_chunks",
        "govern_openai_compatible_call(capability=rerank)",
    ),
    ProviderCallEntry(
        "query_image_vlm",
        "raganything.query.pipeline; raganything.routers.agent",
        "instance vision_model_func -> governed profile builder",
    ),
    ProviderCallEntry(
        "agent_summary_and_fallback",
        "raganything.routers.agent._call_summary_llm; _build_agent_llm",
        "govern_openai_compatible_call",
    ),
    ProviderCallEntry(
        "agentic",
        "raganything.agentic_rag; raganything.routers.agent",
        "selected agent llm -> governed profile builder",
    ),
    ProviderCallEntry(
        "legacy_kb_callbacks",
        "raganything.services.kb_service.create_rag",
        "task snapshot/contextual profile builders",
    ),
    ProviderCallEntry(
        "autorepair",
        "raganything.routers.autorepair",
        "govern_openai_compatible_call",
    ),
    ProviderCallEntry(
        "workflow_execution",
        "raganything.workflow_executor.LLMAnswerExecutor",
        "govern_openai_compatible_call",
    ),
    ProviderCallEntry(
        "upload_background",
        "raganything.services.kb_service.create_rag",
        "profile builders with ProviderPriority.UPLOAD",
    ),
    ProviderCallEntry(
        "text_embedding",
        "raganything.services.kb_service.create_rag",
        "govern_openai_compatible_call(capability=embedding)",
    ),
)


def inventory_identifiers() -> frozenset[str]:
    return frozenset(entry.identifier for entry in QWEN_PROVIDER_CALL_INVENTORY)


__all__ = ["ProviderCallEntry", "QWEN_PROVIDER_CALL_INVENTORY", "inventory_identifiers"]
