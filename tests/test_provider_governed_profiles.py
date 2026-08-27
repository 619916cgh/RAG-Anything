import json

import pytest

from raganything.services import vision_models
from raganything.services.provider_governance import ProviderPriority


class _FakeGovernor:
    def __init__(self):
        self.calls = []

    async def governed_call(self, policy, call, **kwargs):
        self.calls.append(("call", policy, kwargs))
        return await call()

    def governed_stream(self, policy, call, **kwargs):
        self.calls.append(("stream", policy, kwargs))

        async def run():
            result = await call()
            if hasattr(result, "__aiter__"):
                async for item in result:
                    yield item
            else:
                yield result

        return run()


@pytest.mark.asyncio
async def test_qwen_llm_and_vlm_builders_use_governor_without_public_fields(tmp_path, monkeypatch):
    catalog = tmp_path / "profiles.json"
    catalog.write_text(json.dumps({"profiles": [
        {"id": "qwen-llm", "kind": "llm", "display_name": "Qwen", "provider": "openai_compatible", "model": "qwen-plus", "private": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key_env": "QWEN_TEST_KEY"}},
        {"id": "qwen-vlm", "kind": "vlm", "display_name": "Qwen V", "provider": "openai_compatible", "model": "qwen-vl-plus", "private": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key_env": "QWEN_TEST_KEY"}},
    ]}), encoding="utf-8")
    monkeypatch.setenv("MODEL_PROFILE_CATALOG_FILE", str(catalog))
    monkeypatch.setenv("QWEN_TEST_KEY", "temporary-secret-value")
    vision_models.reset_catalog_cache()
    fake = _FakeGovernor()
    monkeypatch.setattr(vision_models, "_PROVIDER_GOVERNOR", fake)

    async def completion(*args, **kwargs):
        return "answer"

    llm = vision_models.build_llm_callable("qwen-llm", completion_func=completion)
    assert await llm("question") == "answer"
    vlm = vision_models.build_vlm_callable("qwen-vlm", completion_func=completion)
    assert await vlm("question") == "answer"
    assert [entry[0] for entry in fake.calls] == ["call", "call"]
    assert all(entry[1].concurrency_limit == 40 for entry in fake.calls)
    encoded = json.dumps([profile.model_dump() for profile in vision_models.list_model_profiles()])
    assert "concurrency_limit" not in encoded
    assert "temporary-secret-value" not in encoded
    vision_models.reset_catalog_cache()


@pytest.mark.asyncio
async def test_legacy_qwen_fallback_rejects_when_no_available_profile(tmp_path, monkeypatch):
    catalog = tmp_path / "profiles.json"
    catalog.write_text(json.dumps({"profiles": [{
        "id": "qwen-disabled", "kind": "llm", "display_name": "Qwen",
        "provider": "openai_compatible", "model": "qwen-plus",
        "private": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key_env": "MISSING_QWEN_KEY"},
    }]}), encoding="utf-8")
    monkeypatch.setenv("MODEL_PROFILE_CATALOG_FILE", str(catalog))
    vision_models.reset_catalog_cache()

    async def unexpected_call():
        raise AssertionError("unavailable Qwen profile must not call upstream")

    with pytest.raises(Exception) as caught:
        await vision_models.govern_openai_compatible_call(
            "qwen-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1", unexpected_call
        )
    assert getattr(caught.value, "code", None) == "provider_unavailable"
    vision_models.reset_catalog_cache()


@pytest.mark.asyncio
async def test_qwen_embedding_catalog_profile_uses_governor(tmp_path, monkeypatch):
    catalog = tmp_path / "profiles.json"
    catalog.write_text(json.dumps({"profiles": [{
        "id": "qwen-embedding", "kind": "embedding", "display_name": "Qwen embedding",
        "provider": "openai_compatible", "model": "text-embedding-v4", "embedding_dim": 1024,
        "private": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key_env": "QWEN_TEST_KEY"},
    }]}), encoding="utf-8")
    monkeypatch.setenv("MODEL_PROFILE_CATALOG_FILE", str(catalog))
    monkeypatch.setenv("QWEN_TEST_KEY", "temporary-secret-value")
    vision_models.reset_catalog_cache()
    fake = _FakeGovernor()
    monkeypatch.setattr(vision_models, "_PROVIDER_GOVERNOR", fake)

    async def completion():
        return [[0.0]]

    assert await vision_models.govern_openai_compatible_call(
        "text-embedding-v4", "https://dashscope.aliyuncs.com/compatible-mode/v1", completion,
        capability="embedding", priority=ProviderPriority.UPLOAD,
    ) == [[0.0]]
    assert fake.calls[0][0] == "call"
    assert fake.calls[0][1].capability == "embedding"
    vision_models.reset_catalog_cache()


def test_qwen_fanout_is_clamped_by_private_governance_policy(tmp_path, monkeypatch):
    catalog = tmp_path / "profiles.json"
    catalog.write_text(json.dumps({"profiles": [{
        "id": "qwen-llm", "kind": "llm", "display_name": "Qwen",
        "provider": "openai_compatible", "model": "qwen-plus",
        "private": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key_env": "QWEN_TEST_KEY"},
    }]}), encoding="utf-8")
    monkeypatch.setenv("MODEL_PROFILE_CATALOG_FILE", str(catalog))
    monkeypatch.setenv("QWEN_TEST_KEY", "temporary-secret-value")
    monkeypatch.setenv("PROVIDER_GOVERNANCE_QWEN_CONCURRENCY_LIMIT", "3")
    vision_models.reset_catalog_cache()

    assert vision_models.effective_qwen_fanout("qwen-llm", 16) == 3
    assert vision_models.effective_qwen_fanout("qwen-llm", 2) == 2
    vision_models.reset_catalog_cache()


def test_qwen_quota_is_private_and_requires_explicit_verified_pair(tmp_path, monkeypatch):
    catalog = tmp_path / "profiles.json"
    catalog.write_text(json.dumps({"profiles": [{
        "id": "qwen-llm", "kind": "llm", "display_name": "Qwen",
        "provider": "openai_compatible", "model": "qwen-plus",
        "private": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key_env": "QWEN_TEST_KEY"},
    }]}), encoding="utf-8")
    monkeypatch.setenv("MODEL_PROFILE_CATALOG_FILE", str(catalog))
    monkeypatch.setenv("QWEN_TEST_KEY", "temporary-secret-value")
    monkeypatch.setenv("PROVIDER_GOVERNANCE_QWEN_REQUESTS_PER_MINUTE", "123")
    monkeypatch.setenv("PROVIDER_GOVERNANCE_QWEN_TOKENS_PER_MINUTE", "456789")
    vision_models.reset_catalog_cache()
    entry = vision_models.require_available("qwen-llm", "llm")

    unverified = vision_models._qwen_policy(entry, "llm")
    assert not unverified.quota_verified
    assert unverified.requests_per_minute is None
    assert unverified.tokens_per_minute is None

    monkeypatch.setenv("PROVIDER_GOVERNANCE_QWEN_QUOTA_VERIFIED", "true")
    verified = vision_models._qwen_policy(entry, "llm")
    assert verified.quota_verified
    assert verified.requests_per_minute == 123
    assert verified.tokens_per_minute == 456789
    encoded = json.dumps([profile.model_dump() for profile in vision_models.list_model_profiles()])
    for forbidden in ("requests_per_minute", "tokens_per_minute", "quota_verified", "456789"):
        assert forbidden not in encoded
    vision_models.reset_catalog_cache()


def test_verified_qwen_quota_rejects_an_incomplete_configuration(tmp_path, monkeypatch):
    catalog = tmp_path / "profiles.json"
    catalog.write_text(json.dumps({"profiles": [{
        "id": "qwen-llm", "kind": "llm", "display_name": "Qwen",
        "provider": "openai_compatible", "model": "qwen-plus",
        "private": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key_env": "QWEN_TEST_KEY"},
    }]}), encoding="utf-8")
    monkeypatch.setenv("MODEL_PROFILE_CATALOG_FILE", str(catalog))
    monkeypatch.setenv("QWEN_TEST_KEY", "temporary-secret-value")
    monkeypatch.setenv("PROVIDER_GOVERNANCE_QWEN_QUOTA_VERIFIED", "true")
    vision_models.reset_catalog_cache()

    with pytest.raises(ValueError, match="requires RPM and TPM"):
        vision_models._qwen_policy(vision_models.require_available("qwen-llm", "llm"), "llm")
    vision_models.reset_catalog_cache()
