import pytest


@pytest.mark.asyncio
async def test_legacy_preview_is_read_only_and_requires_strict_evidence(monkeypatch):
    from raganything.routers import knowledge

    statuses = {
        "ready": {"status": "completed", "chunks_list": ["chunk-1"], "metadata": {}},
        "failed": {"status": "completed", "chunks_list": ["chunk-2"], "metadata": {"last_error": "old"}},
        "pending": {"status": "processing", "chunks_list": ["chunk-3"], "metadata": {}},
        "empty": {"status": "completed", "chunks_list": [], "metadata": {}},
    }
    calls = []

    async def load_status(kb):
        calls.append(("status", kb))
        return statuses

    async def quality(kb, doc_id):
        calls.append(("quality", kb, doc_id))
        return {"ready": doc_id == "ready", "reason_code": "missing_vectors"}

    monkeypatch.setattr(knowledge, "_load_doc_status_json", load_status)
    monkeypatch.setattr(knowledge, "evaluate_document_retrieval_health", quality)
    result = await knowledge.legacy_document_readiness_preview(kb="permitted")

    assert result["candidates"] == [{"doc_id": "ready", "reason_code": "verified_legacy_ready"}]
    assert result["excluded_counts"] == {
        "failure_evidence": 1,
        "non_terminal": 1,
        "missing_chunk_evidence": 1,
    }
    assert calls == [("status", "permitted"), ("quality", "permitted", "ready")]
    assert statuses["ready"]["metadata"] == {}
