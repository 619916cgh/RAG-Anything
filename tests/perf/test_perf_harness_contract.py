import asyncio
from pathlib import Path

from tests.perf.mock_provider import (
    EmbeddingRequest,
    MultimodalEmbeddingRequest,
    embeddings,
    multimodal_embeddings,
)


ROOT = Path(__file__).parents[2]


def test_mock_embeddings_are_deterministic_and_dimensioned():
    result = asyncio.run(
        embeddings(EmbeddingRequest(input=["one", "two"], model="perf-mock"), None)
    )
    assert [item["index"] for item in result["data"]] == [0, 1]
    assert len(result["data"][0]["embedding"]) == 1536
    assert result["data"][0]["embedding"] == asyncio.run(
        embeddings(EmbeddingRequest(input="one", model="perf-mock"), None)
    )["data"][0]["embedding"]


def test_mock_multimodal_embeddings_are_dimensioned():
    result = asyncio.run(
        multimodal_embeddings(
            MultimodalEmbeddingRequest(
                input=[{"type": "text", "text": "one"}], model="perf-mock", dimensions=1536
            ),
            None,
        )
    )
    assert len(result["data"][0]["embedding"]) == 1536


def test_perf_compose_never_inherits_the_main_environment_or_names():
    content = (ROOT / "tests" / "perf" / "compose.query.perf.yml").read_text(encoding="utf-8")
    assert "env_file:" not in content
    assert "container_name:" not in content
    assert "LLM_BINDING_HOST: http://mock-provider:18000/v1" in content
    assert "ENABLE_METRICS: \"true\"" in content
    assert "VISION_EMBEDDING_HOST: http://mock-provider:18000/v1" in content
    assert "mem_limit:" in content
    assert "pids_limit:" in content
    assert "raganything.perf.run-id" in content
    assert "/app/server.py:ro" in content
    assert "/app/raganything/runtime_metrics.py:ro" in content
    assert "marker:" not in content
    assert "nginx:" not in content


def test_query_workload_requires_runtime_only_credentials_and_one_sse_statistic():
    content = (ROOT / "tests" / "perf" / "locust_query.py").read_text(encoding="utf-8")
    assert 'os.environ["RAG_CREDENTIALS_FILE"]' in content
    assert 'os.environ["RAG_PERF_RUN_DIR"]' in content
    assert content.count("events.request.fire(") == 1
    assert "started = time.perf_counter()" in content


def test_low_resource_runner_uses_manifest_owned_query_profile_without_builds():
    content = (ROOT / "scripts" / "run_perf_harness.ps1").read_text(encoding="utf-8")
    assert "compose.query.perf.yml" in content
    assert "manifest.json" in content
    assert "raganything.perf.run-id" in content
    assert "--build" not in content
    assert "--remove-orphans" not in content
    assert "Assert-OwnedResources" in content
    assert "com.docker.compose.project" in content
    assert "raganything.perf.run-id" in content
    assert "credentials.json" in content
    assert "Assert-UploadHeadroom" in content


def test_query_smoke_persists_event_level_redacted_outcomes():
    content = (ROOT / "scripts" / "run_perf_query_smoke.py").read_text(encoding="utf-8")
    assert "query-outcomes.ndjson" in content
    assert '"retrieval_only": False' in content
    assert '"ttfb_ms"' in content
    assert '"ttft_ms"' in content
    assert '"done_without_token"' in content
    assert "def _login(" in content
