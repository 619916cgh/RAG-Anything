from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from raganything.routers import agent as agent_router
from raganything.services import pg_agent_repo, user_settings


@pytest.fixture(autouse=True)
def stable_authenticated_sse_session(monkeypatch):
    async def session_is_current(_current_user):
        return True

    monkeypatch.setattr(
        "raganything.dependencies.account_session_is_current", session_is_current
    )


def _resolved_settings():
    return user_settings.ResolvedUserSettings(
        models=user_settings.ModelSelection(
            llm_profile_id="test-llm", vlm_profile_id="test-vlm"
        ),
        ingestion=user_settings.ProcessingTaskSettings(
            parser="docling",
            chunking_strategy="recursive",
            chunk_size=800,
            enable_image=True,
            enable_table=True,
            enable_equation=True,
            enable_video=False,
            entity_types=(),
            minimum_relation_degree=0,
        ),
        retrieval=user_settings.RetrievalOptions(
            preset="balanced",
            rrf_k=60,
            bm25_top_k=50,
            vector_top_k=100,
            graph_top_k=30,
            graph_depth=2,
            channels=("bm25", "vector", "graph"),
            bm25_tokenizer="jieba",
            bm25_k1=1.5,
            bm25_b=0.75,
        ),
        runtime=user_settings.QuotaOptions(
            llm_timeout=180, personal_concurrency=2
        ),
        revision=1,
        fingerprint="settings-fingerprint",
        profile_fingerprints=user_settings.ModelProfileFingerprints(
            llm="llm-fingerprint", vlm="vlm-fingerprint"
        ),
    )


def _stub_runtime_services(monkeypatch, vision_models, *, llm_func=None, vlm_available=True):
    async def resolve_settings(_user_id, **_kwargs):
        return _resolved_settings()

    async def platform_settings():
        return {"settings": {"limits": {"interactive_wait_seconds": 0}}}

    async def available_sections(_user_id):
        return []

    async def acquire_lease(*_args, **_kwargs):
        return "lease-1"

    async def lease_ok(*_args, **_kwargs):
        return True

    async def query_scope(*_args, **_kwargs):
        return {
            "workspace": "kb-alpha",
            "corpus_revision": "revision-1",
            "permission_scope": "user:7",
            "settings_fingerprint": "settings-fingerprint",
            "llm_profile_fingerprint": "llm-fingerprint",
        }

    monkeypatch.setattr(user_settings, "resolve_user_settings_for_task", resolve_settings)
    monkeypatch.setattr(user_settings, "available_sections_for_user", available_sections)
    monkeypatch.setattr(user_settings, "get_platform_settings", platform_settings)
    monkeypatch.setattr(user_settings, "acquire_quota_lease", acquire_lease)
    monkeypatch.setattr(user_settings, "heartbeat_quota_lease", lease_ok)
    monkeypatch.setattr(user_settings, "release_quota_lease", lease_ok)
    monkeypatch.setattr(agent_router, "_query_cache_scope", query_scope)
    monkeypatch.setattr(
        vision_models,
        "require_available",
        lambda _profile_id, kind: (
            (_ for _ in ()).throw(RuntimeError("vlm unavailable"))
            if kind == "vlm" and not vlm_available
            else SimpleNamespace(
                profile=SimpleNamespace(kind=kind, available=True),
                fingerprint=f"{kind}-fingerprint",
            )
        ),
    )
    monkeypatch.setattr(
        vision_models,
        "build_llm_callable",
        lambda *_args, **_kwargs: llm_func,
    )
    monkeypatch.setattr(vision_models, "activate_llm_selection", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(vision_models, "reset_llm_snapshot", lambda _token: None)


def _query_lease(instance):
    async def release():
        return None

    return SimpleNamespace(instance=instance, release=release)


def _make_agent(**overrides):
    agent = {
        "id": "agent-1",
        "name": "Agent One",
        "icon": "A",
        "description": "original description",
        "welcome_message": "hello",
        "kb_name": "kb-alpha",
        "llm_model": "qwen-plus",
        "temperature": 0.3,
        "max_response_tokens": 2048,
        "query_mode": "hybrid",
        "agent_mode": "none",
        "retrieval_top_k": 40,
        "chunk_top_k": 20,
        "enable_rerank": False,
        "include_references": True,
        "answer_completeness_guard_enabled": False,
        "default_tag_id": None,
        "system_prompt": "custom instructions",
        "use_default_prompt": True,
        "owner_id": 7,
        "owner_username": "alice",
        "template_id": "",
        "created_at": "2026-07-08T00:00:00+00:00",
        "updated_at": "2026-07-08T00:00:00+00:00",
    }
    agent.update(overrides)
    return agent


class _DummyRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


async def _consume_streaming_response(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


@pytest.mark.asyncio
async def test_update_agent_preserves_empty_string_clears_and_omits_unsent_fields(monkeypatch):
    current_user = {"id": 7, "username": "alice", "is_admin": False}
    existing_agent = _make_agent()
    captured = {}

    async def fake_get_agent(agent_id):
        assert agent_id == "agent-1"
        return dict(existing_agent)

    async def fake_update_agent(agent_id, updates):
        captured["agent_id"] = agent_id
        captured["updates"] = dict(updates)
        merged = dict(existing_agent)
        merged.update(updates)
        return merged

    async def unexpected_verify_kb_access(**_kwargs):
        raise AssertionError("verify_kb_access should not run when kb_name is omitted")

    async def fake_resolve_tag_scope(kb_name, tag_id):
        assert kb_name == "kb-alpha"
        assert tag_id == 5
        return SimpleNamespace(tag_id=5, tag_name="default scope")

    monkeypatch.setattr(agent_router, "pg_get_agent", fake_get_agent)
    monkeypatch.setattr(agent_router, "pg_update_agent", fake_update_agent)
    monkeypatch.setattr(agent_router, "verify_kb_access", unexpected_verify_kb_access)
    monkeypatch.setattr(agent_router, "resolve_tag_scope", fake_resolve_tag_scope)

    response = await agent_router.update_agent(
        "agent-1",
        agent_router.AgentUpdateRequest(
            description="",
            welcome_message="",
            llm_model="qwen-max",
            answer_completeness_guard_enabled=True,
            default_tag_id=5,
        ),
        current_user=current_user,
        _perm=None,
    )

    assert captured["agent_id"] == "agent-1"
    assert captured["updates"] == {
        "description": "",
        "welcome_message": "",
        "llm_model": "qwen-max",
        "answer_completeness_guard_enabled": True,
        "default_tag_id": 5,
    }
    assert response["agent"]["description"] == ""
    assert response["agent"]["welcome_message"] == ""
    assert response["agent"]["llm_model"] == "qwen-max"


@pytest.mark.asyncio
async def test_update_agent_persists_explicit_guard_disable(monkeypatch):
    current_user = {"id": 7, "username": "alice", "is_admin": False}
    existing_agent = _make_agent(answer_completeness_guard_enabled=True)
    captured = {}

    async def fake_get_agent(_agent_id):
        return dict(existing_agent)

    async def fake_update_agent(_agent_id, updates):
        captured.update(updates)
        merged = dict(existing_agent)
        merged.update(updates)
        return merged

    monkeypatch.setattr(agent_router, "pg_get_agent", fake_get_agent)
    monkeypatch.setattr(agent_router, "pg_update_agent", fake_update_agent)

    response = await agent_router.update_agent(
        "agent-1",
        agent_router.AgentUpdateRequest(
            answer_completeness_guard_enabled=False,
        ),
        current_user=current_user,
        _perm=None,
    )

    assert captured == {"answer_completeness_guard_enabled": False}
    assert response["agent"]["answer_completeness_guard_enabled"] is False


@pytest.mark.asyncio
async def test_update_agent_clears_default_tag_scope(monkeypatch):
    current_user = {"id": 7, "username": "alice", "is_admin": False}
    existing_agent = _make_agent(default_tag_id=5)
    captured = {}

    async def fake_get_agent(_agent_id):
        return dict(existing_agent)

    async def fake_update_agent(_agent_id, updates):
        captured.update(updates)
        merged = dict(existing_agent)
        merged.update(updates)
        return merged

    monkeypatch.setattr(agent_router, "pg_get_agent", fake_get_agent)
    monkeypatch.setattr(agent_router, "pg_update_agent", fake_update_agent)

    response = await agent_router.update_agent(
        "agent-1",
        agent_router.AgentUpdateRequest(default_tag_id=None),
        current_user=current_user,
        _perm=None,
    )

    assert captured == {"default_tag_id": None}
    assert response["agent"]["default_tag_id"] is None


@pytest.mark.asyncio
async def test_update_agent_rejects_forbidden_kb_change_before_persisting(monkeypatch):
    current_user = {"id": 7, "username": "alice", "is_admin": False}
    update_called = {"value": False}

    async def fake_get_agent(_agent_id):
        return _make_agent()

    async def fake_verify_kb_access(**_kwargs):
        raise HTTPException(status_code=403, detail="forbidden kb")

    async def fake_update_agent(_agent_id, _updates):
        update_called["value"] = True
        return _make_agent()

    monkeypatch.setattr(agent_router, "pg_get_agent", fake_get_agent)
    monkeypatch.setattr(agent_router, "verify_kb_access", fake_verify_kb_access)
    monkeypatch.setattr(agent_router, "pg_update_agent", fake_update_agent)

    with pytest.raises(HTTPException) as exc_info:
        await agent_router.update_agent(
            "agent-1",
            agent_router.AgentUpdateRequest(kb_name="kb-forbidden"),
            current_user=current_user,
            _perm=None,
        )

    assert exc_info.value.status_code == 403
    assert update_called["value"] is False


@pytest.mark.asyncio
async def test_pg_update_agent_does_not_resurrect_legacy_json_agent(monkeypatch):
    class FakePool:
        def __init__(self):
            self.calls = []

        async def fetchrow(self, sql, *values):
            self.calls.append((sql, values))
            return None

    pool = FakePool()
    monkeypatch.setattr(pg_agent_repo, "_get_pool", lambda: pool)
    monkeypatch.setattr(
        pg_agent_repo,
        "_json_get_agent",
        lambda _agent_id: (_ for _ in ()).throw(
            AssertionError("legacy JSON must not be read")
        ),
    )

    updated = await pg_agent_repo.pg_update_agent(
        "legacy-agent",
        {"name": "Updated Legacy Agent", "description": "", "llm_model": "qwen-max"},
    )

    assert updated is None
    assert len(pool.calls) == 1


@pytest.mark.asyncio
async def test_pg_create_agent_persists_answer_completeness_guard_flag(monkeypatch):
    captured = {}

    class Connection:
        async def execute(self, sql, *values):
            captured["sql"] = sql
            captured["values"] = values

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return False

    class Pool:
        def acquire(self):
            return Acquire()

    async def get_agent(agent_id):
        return _make_agent(
            id=agent_id,
            answer_completeness_guard_enabled=True,
            default_tag_id=9,
        )

    monkeypatch.setattr(pg_agent_repo, "_get_pool", lambda: Pool())
    monkeypatch.setattr(pg_agent_repo, "pg_get_agent", get_agent)

    created = await pg_agent_repo.pg_create_agent(
        {
            "id": "agent-guard",
            "name": "Guard Agent",
            "answer_completeness_guard_enabled": True,
            "default_tag_id": 9,
        }
    )

    assert "answer_completeness_guard_enabled" in captured["sql"]
    assert captured["values"][15] is True
    assert captured["values"][16] == 9
    assert created["answer_completeness_guard_enabled"] is True
    assert created["default_tag_id"] == 9


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_mode", ["none", "react", "cot"])
async def test_agent_query_stream_uses_latest_agent_runtime_config_in_all_modes(
    monkeypatch,
    agent_mode,
):
    current_user = {"id": 7, "username": "alice", "is_admin": False}
    runtime_agent = _make_agent(
        llm_model="qwen-max",
        temperature=0.8,
        query_mode="global",
        agent_mode=agent_mode,
        max_response_tokens=2222,
        system_prompt="follow the saved agent instructions",
        use_default_prompt=True,
    )
    expected_system_prompt = agent_router._build_agent_system_prompt(runtime_agent)

    openai_calls = []
    kb_calls = []
    query_core_acquisitions = []
    search_tool_calls = []
    agentic_init = {}
    agentic_contexts = []

    async def fake_openai_complete(model, prompt, **kwargs):
        openai_calls.append({"model": model, "prompt": prompt, **kwargs})
        return "stub answer"

    class FakeKB:
        def __init__(self):
            self.config = SimpleNamespace(
                enforce_citation=False,
                vision_search_enabled=False,
            )

        async def aquery(self, query, mode="hybrid", **kwargs):
            kb_calls.append({"query": query, "mode": mode, "kwargs": kwargs})
            return "[来源 1]\n" + ("context " * 80)

        async def finalize_storages(self):
            return None

    class FakeSearchTool:
        def __init__(self, instance, query_mode, top_k, chunk_top_k, enable_rerank, include_references, tag_scope=None, **kwargs):
            search_tool_calls.append(
                {
                    "instance": instance,
                    "query_mode": query_mode,
                    "top_k": top_k,
                    "chunk_top_k": chunk_top_k,
                    "enable_rerank": enable_rerank,
                    "include_references": include_references,
                    "tag_scope": tag_scope,
                    **kwargs,
                }
            )

    class FakeAgenticRAG:
        def __init__(
            self,
            llm_func,
            max_steps,
            mode,
            max_response_tokens,
            system_prompt_override,
            include_references=True,
        ):
            self.llm_func = llm_func
            self.mode = mode
            agentic_init.update(
                {
                    "max_steps": max_steps,
                    "mode": mode,
                    "max_response_tokens": max_response_tokens,
                    "system_prompt_override": system_prompt_override,
                    "include_references": include_references,
                }
            )

        def register_tool(self, tool):
            self.tool = tool

        async def run_stream(self, query):
            agentic_contexts.append({"mode": "react", "query": query})
            await self.llm_func("react prompt")
            yield SimpleNamespace(
                type="done",
                answer="react answer",
                content=None,
                step=None,
                thought=None,
                action=None,
                observation=None,
                elapsed_ms=None,
            )

        async def run_with_context(self, query, context):
            agentic_contexts.append({"mode": "cot", "context": context})
            await self.llm_func("cot prompt")
            return SimpleNamespace(
                answer="cot answer",
                trace=[
                    SimpleNamespace(
                        step_number=1,
                        thought="reasoning step",
                        elapsed_ms=11,
                    )
                ],
            )

    async def fake_verify_kb_access(kb, current_user):
        assert current_user["id"] == 7
        return kb

    async def fake_acquire_query_kb(_kb_name, **_kwargs):
        query_core_acquisitions.append((_kb_name, _kwargs))
        return _query_lease(FakeKB())

    async def fake_pg_get_agent(_agent_id):
        return dict(runtime_agent)

    async def fake_pg_get_conversation(_agent_id, thread_id):
        return {
            "id": thread_id,
            "owner_id": 7,
            "summary": "previous conversation established the PLC fault context",
            "messages": [],
        }

    async def fake_pg_add_message(*_args, **_kwargs):
        return True

    async def fake_record_query(*_args, **_kwargs):
        return None

    async def fake_recall_query_images(*_args, **_kwargs):
        return [], "", None

    async def fake_generate_summary(*_args, **_kwargs):
        return None

    async def selected_llm(prompt, **kwargs):
        return await fake_openai_complete("profile-model", prompt, **kwargs)

    def discard_background_task(coro):
        coro.close()
        return None

    monkeypatch.setattr(agent_router, "openai_complete_if_cache", fake_openai_complete)
    monkeypatch.setattr(agent_router, "verify_kb_access", fake_verify_kb_access)
    monkeypatch.setattr(agent_router, "acquire_query_kb", fake_acquire_query_kb)
    monkeypatch.setattr(agent_router, "pg_get_agent", fake_pg_get_agent)
    monkeypatch.setattr(agent_router, "pg_get_conversation", fake_pg_get_conversation)
    monkeypatch.setattr(agent_router, "pg_add_message", fake_pg_add_message)
    monkeypatch.setattr(agent_router, "record_query", fake_record_query)
    monkeypatch.setattr(agent_router, "recall_query_images", fake_recall_query_images)
    monkeypatch.setattr(agent_router, "_maybe_generate_summary", fake_generate_summary)
    monkeypatch.setattr(agent_router.asyncio, "create_task", discard_background_task)
    monkeypatch.setattr(agent_router, "validate_query_input", lambda *_args, **_kwargs: None)
    from raganything.services import vision_models
    _stub_runtime_services(monkeypatch, vision_models, llm_func=selected_llm, vlm_available=False)
    monkeypatch.setattr(vision_models, "activate_vlm_selection", lambda _snapshot: None)
    monkeypatch.setattr(vision_models, "reset_vlm_snapshot", lambda _token: None)

    if agent_mode in {"react", "cot"}:
        import raganything.agentic_rag as agentic_module

        monkeypatch.setattr(agentic_module, "AgenticRAG", FakeAgenticRAG)
        monkeypatch.setattr(agentic_module, "SearchTool", FakeSearchTool)

    response = await agent_router.agent_query_stream(
        "agent-1",
        agent_router.AgentQueryRequest(query="Explain the topic", thread_id="thread-1"),
        _DummyRequest(),
        current_user=current_user,
        _perm=None,
    )
    body = await _consume_streaming_response(response)

    assert openai_calls, f"expected llm call for mode={agent_mode}"
    llm_call = openai_calls[0]
    assert llm_call["model"] == "profile-model"
    assert llm_call["system_prompt"] == expected_system_prompt
    assert llm_call["temperature"] == pytest.approx(0.8)
    assert llm_call["max_tokens"] == 2222
    assert '"type": "done"' in body or '"type":"done"' in body
    assert query_core_acquisitions == [
        ("kb-alpha", {"corpus_revision": "revision-1"})
    ]

    if agent_mode == "none":
        assert kb_calls
        assert kb_calls[0]["mode"] == "global"
        assert "previous conversation established the PLC fault context" in llm_call["prompt"]
    elif agent_mode == "react":
        assert agentic_init["mode"] == "react"
        assert agentic_init["system_prompt_override"] == expected_system_prompt
        assert agentic_init["include_references"] is True
        assert search_tool_calls[0]["query_mode"] == "global"
        assert any(
            "previous conversation established the PLC fault context" in item["query"]
            for item in agentic_contexts
        )
    else:
        assert agentic_init["mode"] == "cot"
        assert agentic_init["system_prompt_override"] == expected_system_prompt
        assert agentic_init["include_references"] is True
        assert kb_calls
        assert kb_calls[0]["mode"] == "global"
        assert any(
            "previous conversation established the PLC fault context" in item["context"]
            for item in agentic_contexts
        )


@pytest.mark.asyncio
async def test_llm_model_override_uses_agent_model_and_profile_transport(monkeypatch):
    from raganything.services import vision_models

    calls = []

    async def completion(model, prompt, **kwargs):
        calls.append({"model": model, "prompt": prompt, **kwargs})
        return "ok"

    entry = vision_models._CatalogEntry(
        profile=vision_models.VisionModelProfile(
            id="llm-profile",
            kind="llm",
            display_name="Profile model",
            provider="openai_compatible",
            model="profile-model",
            available=True,
        ),
        base_url="https://provider.example/v1",
        api_key_env="TEST_AGENT_LLM_KEY",
        timeout=17,
        concurrency=3,
    )
    monkeypatch.setenv("TEST_AGENT_LLM_KEY", "test-secret")
    monkeypatch.setattr(
        vision_models, "require_available", lambda *_args, **_kwargs: entry
    )
    monkeypatch.setattr(vision_models, "_is_qwen_profile", lambda _entry: False)

    selected = vision_models.build_llm_callable(
        "llm-profile",
        completion_func=completion,
        cache_scope="agent-model-override",
        model_override="qwen-max",
    )
    await selected("direct prompt")
    resolved = vision_models.resolve_llm_entry("llm-profile", "qwen-max")
    token = vision_models.activate_llm_selection(
        resolved,
        cache_scope="agent-model-override",
        timeout=17,
        profile_id="llm-profile",
    )
    try:
        context_callable = vision_models.build_contextual_llm_callable(
            "llm-profile",
            completion_func=completion,
        )
        await context_callable("context prompt")
    finally:
        vision_models.reset_llm_snapshot(token)

    assert selected.model_name == "qwen-max"
    assert selected.model_profile_fingerprint == resolved.fingerprint
    assert calls[0]["model"] == "qwen-max"
    assert calls[0]["api_key"] == "test-secret"
    assert calls[0]["base_url"] == "https://provider.example/v1"
    assert calls[0]["timeout"] == 17
    assert calls[1]["model"] == "qwen-max"


def test_agent_api_rejects_invalid_modes_and_model_names():
    with pytest.raises(ValidationError):
        agent_router.AgentCreateRequest(query_mode="unknown")
    with pytest.raises(ValidationError):
        agent_router.AgentCreateRequest(agent_mode="unknown")
    with pytest.raises(ValidationError):
        agent_router.AgentCreateRequest(llm_model=" ")
    with pytest.raises(ValidationError):
        agent_router.AgentCreateRequest(llm_model="bad\nmodel")
    with pytest.raises(ValidationError):
        agent_router.AgentQueryRequest(query="question", mode="unknown")
    with pytest.raises(ValidationError):
        agent_router.AgentQueryRequest(
            query="question",
            run_cache_scope="bad scope",
        )


def test_standard_agent_query_schema_rejects_internal_override_fields():
    standard = agent_router.StandardAgentQueryRequest(
        query="question", thread_id="thread-1"
    )

    assert standard.model_dump() == {
        "query": "question",
        "thread_id": "thread-1",
    }
    with pytest.raises(ValidationError):
        agent_router.StandardAgentQueryRequest(
            query="question", retrieval_only=True
        )
    with pytest.raises(ValidationError):
        agent_router.StandardAgentQueryRequest(query="question", mode="hybrid")
    assert agent_router.AgentQueryRequest(
        query="question", retrieval_only=True
    ).retrieval_only is True


def test_agent_runtime_config_reads_persistent_completeness_guard_flag():
    runtime = agent_router._agent_runtime_config(
        {"answer_completeness_guard_enabled": True}
    )

    assert runtime["answer_completeness_guard_enabled"] is True


def test_effective_agent_tag_scope_supports_default_and_whole_kb_override():
    resolve = agent_router._effective_agent_tag_id

    assert resolve(None, 7) == 7
    assert resolve(9, 7) == 9
    assert resolve(0, 7) is None
    assert resolve(None, None) is None
    with pytest.raises(HTTPException) as exc_info:
        resolve(None, "invalid")
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_agent_llm_honors_explicit_guard_temperature():
    captured = {}

    async def selected_llm(prompt, **kwargs):
        captured.update(kwargs)
        return "ok"

    llm = agent_router._build_agent_llm(
        {
            "max_response_tokens": 512,
            "temperature": 0.8,
            "system_prompt": "system",
            "llm_model": "qwen-plus",
        },
        selected_llm=selected_llm,
    )

    await llm("prompt", temperature=0)

    assert captured["temperature"] == 0


@pytest.mark.asyncio
async def test_retrieval_only_query_emits_metadata_without_history_or_generation(monkeypatch):
    current_user = {"id": 7, "username": "alice", "is_admin": False}
    agent = _make_agent(agent_mode="none")
    calls = {"aquery": 0}

    class FakeKB:
        config = SimpleNamespace(enforce_citation=False, vision_search_enabled=False)

        async def aquery(self, *_args, **_kwargs):
            calls["aquery"] += 1
            return "[来源 1]\n" + ("context " * 40)

        async def finalize_storages(self):
            return None

    async def fake_get_agent(_agent_id):
        return dict(agent)

    async def fake_verify_kb_access(kb, current_user):
        return kb

    async def fake_acquire_query_kb(_kb_name, **_kwargs):
        return _query_lease(FakeKB())

    def unexpected(*_args, **_kwargs):
        raise AssertionError("retrieval_only must not create history, write history, or call generation")

    from raganything.services import vision_models

    monkeypatch.setattr(agent_router, "pg_get_agent", fake_get_agent)
    monkeypatch.setattr(agent_router, "verify_kb_access", fake_verify_kb_access)
    monkeypatch.setattr(agent_router, "acquire_query_kb", fake_acquire_query_kb)
    monkeypatch.setattr(agent_router, "pg_create_conversation", unexpected)
    monkeypatch.setattr(agent_router, "pg_get_conversation", unexpected)
    monkeypatch.setattr(agent_router, "record_query", unexpected)
    monkeypatch.setattr(agent_router, "pg_add_message", unexpected)
    monkeypatch.setattr(agent_router, "validate_query_input", lambda *_args, **_kwargs: None)
    _stub_runtime_services(monkeypatch, vision_models)
    monkeypatch.setattr(vision_models, "activate_vlm_selection", lambda _snapshot: None)
    monkeypatch.setattr(vision_models, "reset_vlm_snapshot", lambda _token: None)

    response = await agent_router.agent_query_stream(
        "agent-1",
        agent_router.AgentQueryRequest(query="Explain the topic", retrieval_only=True),
        _DummyRequest(),
        current_user=current_user,
        _perm=None,
    )
    body = await _consume_streaming_response(response)

    assert calls["aquery"] == 1
    assert '"type": "retrieval"' in body
    assert '"context_present": true' in body
    assert '"type": "done"' in body
    assert "context context" not in body


@pytest.mark.asyncio
async def test_image_query_uses_vlm_and_persists_preview_with_tag_scope(monkeypatch):
    import base64
    import io
    from PIL import Image

    current_user = {"id": 7, "username": "alice", "is_admin": False}
    agent = _make_agent(agent_mode="none", default_tag_id=3)
    saved_messages = []
    vlm_calls = []
    tag_queries = []
    llm_prompts = []
    llm_system_prompts = []

    image_buffer = io.BytesIO()
    Image.new("RGB", (800, 400), "red").save(image_buffer, format="PNG")
    image_data_uri = (
        "data:image/png;base64,"
        + base64.b64encode(image_buffer.getvalue()).decode("ascii")
    )

    class FakeKB:
        config = SimpleNamespace(enforce_citation=False, vision_search_enabled=False)

        async def vision_model_func(
            self,
            prompt,
            system_prompt=None,
            history_messages=None,
            image_data=None,
            image_mime_type=None,
            **_kwargs,
        ):
            vlm_calls.append({
                "prompt": prompt,
                "system_prompt": system_prompt,
                "image_data": image_data,
                "image_mime_type": image_mime_type,
            })
            return "图片中是一个纯红色矩形。"

        async def finalize_storages(self):
            return None

    async def fake_get_agent(_agent_id):
        return dict(agent)

    async def fake_verify_kb_access(kb, current_user):
        assert current_user["id"] == 7
        return kb

    async def fake_acquire_query_kb(_kb_name, **_kwargs):
        return _query_lease(FakeKB())

    async def fake_pg_get_conversation(_agent_id, thread_id):
        return {"id": thread_id, "owner_id": 7, "messages": []}

    async def fake_pg_add_message(_agent_id, _thread_id, message):
        saved_messages.append(dict(message))
        return True

    async def fake_resolve_tag_scope(_kb_name, _tag_id):
        assert _tag_id == 3
        return SimpleNamespace(tag_id=3, tag_name="测试标签")

    async def fake_retrieve_tag_scoped_context(_instance, _tag_scope, _query, **_kwargs):
        tag_queries.append(_query)
        return "[来源 1]\n" + ("标签上下文 " * 40)

    async def selected_llm(prompt, **kwargs):
        llm_prompts.append(prompt)
        llm_system_prompts.append(kwargs.get("system_prompt") or "")
        return "图片中是一个纯红色矩形。"

    def discard_background_task(coro):
        coro.close()
        return None

    from raganything.services import vision_models

    monkeypatch.setattr(agent_router, "pg_get_agent", fake_get_agent)
    monkeypatch.setattr(agent_router, "verify_kb_access", fake_verify_kb_access)
    monkeypatch.setattr(agent_router, "acquire_query_kb", fake_acquire_query_kb)
    monkeypatch.setattr(agent_router, "pg_get_conversation", fake_pg_get_conversation)
    monkeypatch.setattr(agent_router, "pg_add_message", fake_pg_add_message)

    async def fake_record_query(*_args, **_kwargs):
        return None

    monkeypatch.setattr(agent_router, "record_query", fake_record_query)
    monkeypatch.setattr(agent_router, "resolve_tag_scope", fake_resolve_tag_scope)
    monkeypatch.setattr(
        agent_router, "retrieve_tag_scoped_context", fake_retrieve_tag_scoped_context
    )
    monkeypatch.setattr(agent_router, "validate_query_input", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent_router.asyncio, "create_task", discard_background_task)
    _stub_runtime_services(monkeypatch, vision_models, llm_func=selected_llm)
    monkeypatch.setattr(vision_models, "activate_vlm_selection", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(vision_models, "reset_vlm_snapshot", lambda _token: None)

    response = await agent_router.agent_query_stream(
        "agent-1",
        agent_router.AgentQueryRequest(
            query="请描述这张图片",
            thread_id="thread-1",
            image=image_data_uri,
        ),
        _DummyRequest(),
        current_user=current_user,
        _perm=None,
    )
    body = await _consume_streaming_response(response)

    assert len(vlm_calls) == 1, body
    assert vlm_calls[0]["prompt"].startswith("请详细描述这张图片")
    assert vlm_calls[0]["image_data"]
    assert vlm_calls[0]["image_mime_type"] == "image/png"
    assert len(tag_queries) == 1
    assert "图片中是一个纯红色矩形" in llm_prompts[0]
    assert llm_prompts[0].rfind("## 检索内容") < llm_prompts[0].rfind(
        "## 用户上传图片的视觉分析"
    )
    assert "最高优先级直接证据" in llm_system_prompts[0]
    assert "不得用知识库中未出现在视觉分析里的实体覆盖" in llm_system_prompts[0]
    assert '"status": "done"' in body

    user_message = next(message for message in saved_messages if message["role"] == "user")
    assert user_message["image_preview"].startswith("data:image/jpeg;base64,")
    assert "image/" not in user_message["image_preview"].split(",", 1)[1][:20]


@pytest.mark.asyncio
async def test_image_query_reports_vlm_failure_instead_of_silent_done(monkeypatch):
    import base64
    import io
    from PIL import Image

    current_user = {"id": 7, "username": "alice", "is_admin": False}
    saved_messages = []

    image_buffer = io.BytesIO()
    Image.new("RGB", (80, 40), "blue").save(image_buffer, format="PNG")
    image_data_uri = (
        "data:image/png;base64,"
        + base64.b64encode(image_buffer.getvalue()).decode("ascii")
    )

    class FakeKB:
        config = SimpleNamespace(enforce_citation=False, vision_search_enabled=False)

        async def vision_model_func(self, *_args, **_kwargs):
            raise RuntimeError("provider rejected image")

        async def aquery(self, *_args, **_kwargs):
            return "[no-context]"

        async def finalize_storages(self):
            return None

    async def fake_get_agent(_agent_id):
        return _make_agent(agent_mode="none")

    async def fake_verify_kb_access(kb, current_user):
        assert current_user["id"] == 7
        return kb

    async def fake_acquire_query_kb(_kb_name, **_kwargs):
        return _query_lease(FakeKB())

    async def fake_pg_get_conversation(_agent_id, thread_id):
        return {"id": thread_id, "owner_id": 7, "messages": []}

    async def fake_pg_add_message(_agent_id, _thread_id, message):
        saved_messages.append(dict(message))
        return True

    from raganything.services import vision_models

    monkeypatch.setattr(agent_router, "pg_get_agent", fake_get_agent)
    monkeypatch.setattr(agent_router, "verify_kb_access", fake_verify_kb_access)
    monkeypatch.setattr(agent_router, "acquire_query_kb", fake_acquire_query_kb)
    monkeypatch.setattr(agent_router, "pg_get_conversation", fake_pg_get_conversation)
    monkeypatch.setattr(agent_router, "pg_add_message", fake_pg_add_message)

    async def fake_record_query(*_args, **_kwargs):
        return None

    monkeypatch.setattr(agent_router, "record_query", fake_record_query)
    monkeypatch.setattr(agent_router, "validate_query_input", lambda *_args, **_kwargs: None)
    _stub_runtime_services(monkeypatch, vision_models)
    monkeypatch.setattr(
        vision_models, "activate_vlm_selection", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(vision_models, "reset_vlm_snapshot", lambda _token: None)

    response = await agent_router.agent_query_stream(
        "agent-1",
        agent_router.AgentQueryRequest(
            query="这张图片里有什么？",
            thread_id="thread-1",
            image=image_data_uri,
        ),
        _DummyRequest(),
        current_user=current_user,
        _perm=None,
    )
    body = await _consume_streaming_response(response)

    assert '"type": "image_analysis", "status": "error"' in body
    assert "图片理解服务暂时不可用" in body
    assert '"status": "done", "description_preview"' not in body
    user_message = next(message for message in saved_messages if message["role"] == "user")
    assert user_message["image_preview"].startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_image_query_answers_from_vision_when_kb_context_is_empty(monkeypatch):
    import base64
    import io
    from PIL import Image

    current_user = {"id": 7, "username": "alice", "is_admin": False}
    llm_prompts = []
    llm_system_prompts = []

    image_buffer = io.BytesIO()
    Image.new("RGB", (80, 40), "green").save(image_buffer, format="PNG")
    image_data_uri = (
        "data:image/png;base64,"
        + base64.b64encode(image_buffer.getvalue()).decode("ascii")
    )

    class FakeKB:
        config = SimpleNamespace(enforce_citation=False, vision_search_enabled=False)

        async def vision_model_func(self, *_args, **_kwargs):
            return "图片中是一个纯绿色矩形。"

        async def aquery(self, *_args, **_kwargs):
            return "[no-context]"

        async def finalize_storages(self):
            return None

    async def fake_get_agent(_agent_id):
        return _make_agent(agent_mode="none")

    async def fake_verify_kb_access(kb, current_user):
        assert current_user["id"] == 7
        return kb

    async def fake_acquire_query_kb(_kb_name, **_kwargs):
        return _query_lease(FakeKB())

    async def fake_pg_get_conversation(_agent_id, thread_id):
        return {"id": thread_id, "owner_id": 7, "messages": []}

    async def fake_pg_add_message(_agent_id, _thread_id, _message):
        return True

    async def selected_llm(prompt, **kwargs):
        llm_prompts.append(prompt)
        llm_system_prompts.append(kwargs.get("system_prompt") or "")
        return "这是纯绿色矩形。"

    async def fake_record_query(*_args, **_kwargs):
        return None

    from raganything.services import vision_models

    monkeypatch.setattr(agent_router, "pg_get_agent", fake_get_agent)
    monkeypatch.setattr(agent_router, "verify_kb_access", fake_verify_kb_access)
    monkeypatch.setattr(agent_router, "acquire_query_kb", fake_acquire_query_kb)
    monkeypatch.setattr(agent_router, "pg_get_conversation", fake_pg_get_conversation)
    monkeypatch.setattr(agent_router, "pg_add_message", fake_pg_add_message)
    monkeypatch.setattr(agent_router, "record_query", fake_record_query)
    monkeypatch.setattr(agent_router, "validate_query_input", lambda *_args, **_kwargs: None)
    _stub_runtime_services(monkeypatch, vision_models, llm_func=selected_llm)
    monkeypatch.setattr(
        vision_models, "activate_vlm_selection", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(vision_models, "reset_vlm_snapshot", lambda _token: None)

    response = await agent_router.agent_query_stream(
        "agent-1",
        agent_router.AgentQueryRequest(
            query="这张图片是什么颜色？",
            thread_id="thread-1",
            image=image_data_uri,
        ),
        _DummyRequest(),
        current_user=current_user,
        _perm=None,
    )
    body = await _consume_streaming_response(response)

    assert llm_prompts
    assert "图片中是一个纯绿色矩形" in llm_prompts[0]
    assert "视觉分析结果是图片内容的最高优先级直接证据" in llm_system_prompts[0]
    assert "知识库中暂无与您问题相关的数据" not in body
    assert '"image_description": "图片中是一个纯绿色矩形。"' in body
