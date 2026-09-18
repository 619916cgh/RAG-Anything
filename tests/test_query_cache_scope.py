import hashlib

import pytest

from raganything.query_cache import QueryCache, QueryCacheScope
from raganything.routers import agent as agent_router
from raganything.services.query_execution import QueryExecutionScope
from raganything.query.pipeline import QueryMixin


def test_query_cache_scope_separates_permissions_content_and_settings():
    cache = QueryCache(max_size=10)
    base = QueryCacheScope("kb-a", "user:7", "rev-1", "settings-a", "llm-a")
    other_user = QueryCacheScope("kb-a", "user:8", "rev-1", "settings-a", "llm-a")
    other_revision = QueryCacheScope("kb-a", "user:7", "rev-2", "settings-a", "llm-a")
    other_settings = QueryCacheScope("kb-a", "user:7", "rev-1", "settings-b", "llm-a")

    cache.set("where is the report?", {"answer": "private"}, base)

    assert cache.get("where is the report?", base) == {"answer": "private"}
    assert cache.get("where is the report?", other_user) is None
    assert cache.get("where is the report?", other_revision) is None
    assert cache.get("where is the report?", other_settings) is None


def test_query_cache_scope_isolates_evaluation_runs_without_query_changes():
    cache = QueryCache(max_size=10)
    first_run = QueryCacheScope(
        "kb-a",
        "user:7",
        "rev-1",
        "settings-a",
        "llm-a",
        "run-a",
    )
    second_run = QueryCacheScope(
        "kb-a",
        "user:7",
        "rev-1",
        "settings-a",
        "llm-a",
        "run-b",
    )

    cache.set("same question", {"answer": "first"}, first_run)

    assert cache.get("same question", first_run) == {"answer": "first"}
    assert cache.get("same question", second_run) is None


def test_multimodal_cache_key_includes_runtime_scope():
    first = QueryMixin()
    first.query_cache_scope = {
        "workspace": "kb-a",
        "permission_scope": "user:7",
        "corpus_revision": "rev-1",
        "settings_fingerprint": "settings-a",
        "llm_profile_fingerprint": "llm-a",
    }
    other_user = QueryMixin()
    other_user.query_cache_scope = {
        **first.query_cache_scope,
        "permission_scope": "user:8",
    }
    other_revision = QueryMixin()
    other_revision.query_cache_scope = {
        **first.query_cache_scope,
        "corpus_revision": "rev-2",
    }

    key = first._generate_multimodal_cache_key(
        "compare", [{"type": "table", "table_data": "a,b\n1,2"}], "rrf"
    )

    assert key != other_user._generate_multimodal_cache_key(
        "compare", [{"type": "table", "table_data": "a,b\n1,2"}], "rrf"
    )
    assert key != other_revision._generate_multimodal_cache_key(
        "compare", [{"type": "table", "table_data": "a,b\n1,2"}], "rrf"
    )


def test_execution_scope_includes_run_cache_scope_without_changing_legacy_shape():
    legacy = QueryExecutionScope(
        trace_id="trace",
        workspace="kb",
        corpus_revision="rev",
        permission_scope="user:7",
        settings_fingerprint="settings",
        llm_profile_fingerprint="llm",
        deadline_monotonic=1.0,
    )
    run_scoped = QueryExecutionScope(
        trace_id="trace",
        workspace="kb",
        corpus_revision="rev",
        permission_scope="user:7",
        settings_fingerprint="settings",
        llm_profile_fingerprint="llm",
        deadline_monotonic=1.0,
        run_cache_scope="run-a",
    )

    assert len(legacy) == 7
    assert len(run_scoped) == 8
    assert dict(legacy).get("run_cache_scope") is None
    assert dict(run_scoped)["run_cache_scope"] == "run-a"


@pytest.mark.asyncio
async def test_agent_query_scope_hashes_gated_run_identifier(monkeypatch):
    async def content_updates(_kbs):
        return {"kb-a": "revision-1"}

    monkeypatch.setattr(
        agent_router,
        "pg_get_latest_content_updates_batch",
        content_updates,
    )
    monkeypatch.setenv("AGENT_RUN_CACHE_SCOPE_ENABLED", "true")

    scope = await agent_router._query_cache_scope(
        "kb-a",
        user_id=7,
        settings_fingerprint="settings-a",
        llm_profile_fingerprint="llm-a",
        run_cache_scope="run-a",
    )

    expected = hashlib.sha256(b"run-a").hexdigest()[:32]
    assert scope["run_cache_scope"] == expected
    assert "run-a" not in scope.values()

    second = await agent_router._query_cache_scope(
        "kb-a",
        user_id=7,
        settings_fingerprint="settings-a",
        llm_profile_fingerprint="llm-a",
        run_cache_scope="run-b",
    )
    assert second["run_cache_scope"] != scope["run_cache_scope"]


@pytest.mark.asyncio
async def test_agent_query_scope_ignores_run_identifier_when_gate_is_off(monkeypatch):
    async def content_updates(_kbs):
        return {"kb-a": "revision-1"}

    monkeypatch.setattr(
        agent_router,
        "pg_get_latest_content_updates_batch",
        content_updates,
    )
    monkeypatch.delenv("AGENT_RUN_CACHE_SCOPE_ENABLED", raising=False)

    scope = await agent_router._query_cache_scope(
        "kb-a",
        user_id=7,
        settings_fingerprint="settings-a",
        llm_profile_fingerprint="llm-a",
        run_cache_scope="run-a",
    )

    assert "run_cache_scope" not in scope
