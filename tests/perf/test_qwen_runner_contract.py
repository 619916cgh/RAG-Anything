import json
from pathlib import Path

import pytest

from scripts.qwen_embedding_health import _dimensions, _http_family
from scripts.run_profile_b_ladder import QWEN_STAGES, _validate_qwen_environment


ROOT = Path(__file__).parents[2]


def _qwen_environment(tmp_path: Path) -> dict[str, str]:
    quota = tmp_path / "quota.json"
    quota.write_text(
        json.dumps({
            "provider": "qwen", "model": "qwen-plus", "embedding_model": "text-embedding-v4",
            "rpm": 100, "tpm": 100000,
            "model_limits": {
                "qwen-plus": {"rpm": 300, "tpm": 300000},
                "text-embedding-v4": {"rpm": 100, "tpm": 100000},
            },
        }),
        encoding="utf-8",
    )
    return {
        "TMPDIR": str(tmp_path),
        "PERF_QWEN_ENDPOINT": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "PERF_QWEN_API_KEY": "temporary-key-value-not-a-real-key",
        "PERF_QWEN_MODEL": "qwen-plus",
        "PERF_QWEN_EMBEDDING_MODEL": "text-embedding-v4",
        "PERF_QWEN_QUOTA_RECORD": str(quota),
    }


def test_qwen_profile_requires_explicit_temporary_quota_evidence_and_redacts_key(tmp_path, monkeypatch):
    environment = _qwen_environment(tmp_path)
    monkeypatch.setenv("TMPDIR", environment["TMPDIR"])
    validated = _validate_qwen_environment(environment)

    assert QWEN_STAGES == (10, 20, 30, 40, 50)
    assert validated == {
        "endpoint": environment["PERF_QWEN_ENDPOINT"],
        "model": "qwen-plus",
        "embedding_model": "text-embedding-v4",
        "quota_record": environment["PERF_QWEN_QUOTA_RECORD"],
        "rpm": "100",
        "tpm": "100000",
    }
    assert environment["PERF_QWEN_API_KEY"] not in json.dumps(validated)


def test_embedding_health_output_helpers_only_expose_fixed_classification_fields():
    assert _http_family(200) == "2xx"
    assert _http_family(429) == "4xx"
    assert _http_family(503) == "5xx"
    assert _dimensions({"data": [{"embedding": [0.0] * 1024}]}) == [1024]
    assert _dimensions({"data": [{"embedding": "not-a-vector"}]}) == []


@pytest.mark.parametrize("endpoint", [
    "http://dashscope.aliyuncs.com/compatible-mode/v1",
    "https://production.example.test/v1",
    "https://dashscope.aliyuncs.com/compatible-mode/v1?api_key=not-allowed",
])
def test_qwen_profile_rejects_non_isolated_or_credential_bearing_endpoints(tmp_path, monkeypatch, endpoint):
    environment = _qwen_environment(tmp_path)
    environment["PERF_QWEN_ENDPOINT"] = endpoint
    monkeypatch.setenv("TMPDIR", environment["TMPDIR"])
    with pytest.raises(ValueError):
        _validate_qwen_environment(environment)


def test_qwen_quota_record_rejects_a_non_bottleneck_combination(tmp_path, monkeypatch):
    environment = _qwen_environment(tmp_path)
    quota = Path(environment["PERF_QWEN_QUOTA_RECORD"])
    payload = json.loads(quota.read_text(encoding="utf-8"))
    payload["rpm"] = 300
    quota.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("TMPDIR", environment["TMPDIR"])

    with pytest.raises(ValueError, match="bottleneck"):
        _validate_qwen_environment(environment)


def test_qwen_runner_and_compose_keep_mock_as_default_and_record_no_secret_fields():
    runner = (ROOT / "scripts" / "run_profile_b_ladder.py").read_text(encoding="utf-8")
    shell = (ROOT / "scripts" / "run_isolated_cloud_perf.sh").read_text(encoding="utf-8")
    compose = (ROOT / "tests" / "perf" / "compose.cloud.perf.yml").read_text(encoding="utf-8")
    workload = (ROOT / "scripts" / "run_cloud_perf_workload.py").read_text(encoding="utf-8")

    assert 'choices=("mock", "qwen"), default="mock"' in runner
    assert '"qwen provider profile requires one of stages 10, 20, 30, 40, or 50"' in runner
    assert '--diagnose-text-insert' in runner
    assert '"text insert diagnostic requires qwen stage 10 without predecessor or direct mode"' in runner
    assert '"later Profile B stages require an existing sanitized predecessor report"' in runner
    assert '"profile_b_text_insert_diagnostic"' in runner
    assert '"PERF_PROVIDER_PROFILE": args.provider_profile' in runner
    assert 'provider_profile=${PERF_PROVIDER_PROFILE:-mock}' in shell
    assert '"qwen_quota_record_sha256"' in shell
    assert "LLM_BINDING_HOST: ${PERF_LLM_BINDING_HOST:-http://mock-provider:18000/v1}" in compose
    assert "LLM_BINDING_API_KEY: ${PERF_LLM_BINDING_API_KEY:-perf-only}" in compose
    assert "MODEL_PROFILE_CATALOG_FILE: /tmp/perf-model-profiles.json" in compose
    assert "model-profiles.json:/tmp/perf-model-profiles.json:ro" in compose
    assert "model-profiles.json" in shell
    assert "PROVIDER_GOVERNANCE_QWEN_QUOTA_VERIFIED" in compose
    assert "PERF_PROVIDER_GOVERNANCE_QWEN_REQUESTS_PER_MINUTE" in shell
    assert 'manifest["profile_b_result"] = result' in shell
    assert '"profile_b_result", "cleanup_verified"' in shell
    assert '"profile_b_text_insert_diagnostic"' in shell
    assert "PROFILE_B_TTFT_P95_MAX_MS = 5000" in workload
    assert "PROFILE_B_TOTAL_P95_MAX_MS = 15000" in workload
    capacity_image = (ROOT / "tests" / "perf" / "Dockerfile.cloud-qwen-governance-app").read_text(encoding="utf-8")
    profile_image = (ROOT / "tests" / "perf" / "Dockerfile.cloud-qwen-governance-profile").read_text(encoding="utf-8")
    assert "COPY raganything/processor/doc_processor.py /app/raganything/processor/doc_processor.py" in profile_image
    assert "router-10000-v1" in capacity_image
    assert '"5/minute"' in capacity_image and '"10000/minute"' in capacity_image
    assert "base candidate already contains" in profile_image
    assert "EMBEDDING_DIM: ${PERF_EMBEDDING_DIM:-1536}" in compose
    assert 'PERF_EMBEDDING_DIM="1024"' in shell
    ladder = (ROOT / "scripts" / "run_qwen_governance_ladder.sh").read_text(encoding="utf-8")
    assert "for stage in 10 20 30 40 50" in ladder
    assert "read -r -s -p \"Temporary Qwen key: \" PERF_QWEN_API_KEY" in ladder
    assert "--predecessor" in ladder


def test_create_rag_smoke_uses_worker_snapshot_contract_and_fixed_failure_codes():
    runner = (ROOT / "scripts" / "run_profile_b_ladder.py").read_text(encoding="utf-8")

    assert "require_vlm=False" not in runner
    assert "text_embedding_identity_from_environment" in runner
    assert "load_catalog(refresh=True)" in runner
    assert "'profile_fingerprints'" in runner
    assert "'parser':'docling'" in runner
    assert "await rag._ensure_lightrag_initialized()" in runner
    assert "initialized.get('success')" in runner
    assert "rag.insert_content_list" in runner
    assert "timeout=150" in runner
    assert "text_insert_error" in runner
    assert "storage_schema_error" in runner
    assert "ainsert_runtime_error" in runner
    assert '"import asyncio, os, uuid\\n"' in runner
    assert "finalize_timeout" in runner
    assert "finalize_error" in runner
    assert "close_error" in runner
    assert "str(uuid.uuid4())" in runner
    assert "embedding_pipeline_error" in runner
    assert "llm_pipeline_error" in runner
    assert "parser_unavailable" in runner
    assert "worker_vdb_persistence=True" in runner
    for outcome in (
        "snapshot_profile_error", "rag_construct_error", "parser_unavailable",
        "lightrag_init_error", "pg_storage_error",
        "provider_missing", "provider_error", "timeout",
    ):
        assert f"smoke_failure={outcome}" in runner or f"\"{outcome}\"" in runner
