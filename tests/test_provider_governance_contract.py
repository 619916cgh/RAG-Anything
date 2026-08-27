from pathlib import Path

from prometheus_client import CollectorRegistry, generate_latest

from raganything.services.provider_governance import PrometheusMetrics, ProviderPolicy, ProviderPriority


ROOT = Path(__file__).parents[1]


def test_provider_migration_has_only_opaque_governance_columns():
    sql = (ROOT / "migrations" / "036_provider_governance.sql").read_text(encoding="utf-8").lower()

    for required in ("provider_call_leases", "provider_waiters", "provider_circuit_state", "owner_fence", "expires_at"):
        assert required in sql
    columns = "\n".join(
        line.strip().split()[0]
        for line in sql.splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    )
    for forbidden in ("api_key", "endpoint", "prompt", "answer", "user_id", "token"):
        assert forbidden not in columns


def test_central_model_builders_are_the_governed_qwen_entry_points():
    source = (ROOT / "raganything" / "services" / "vision_models.py").read_text(encoding="utf-8")

    assert "def build_llm_callable(" in source
    assert "def build_vlm_callable(" in source
    assert "governed_call(policy, outbound" in source
    assert "governed_stream(policy, outbound" in source
    assert "build_contextual_llm_callable" in source
    assert "build_contextual_vlm_callable" in source


def test_provider_metrics_are_idempotent_and_only_use_safe_labels():
    registry = CollectorRegistry()
    first = PrometheusMetrics(registry=registry)
    second = PrometheusMetrics(registry=registry)
    policy = ProviderPolicy(model="qwen-plus")

    first.observe("provider_rejections_total", 1, {
        "provider": "qwen", "capability": "llm", "profile": policy.fingerprint_hash,
        "priority": ProviderPriority.QUERY.name.lower(), "outcome": "429",
    })
    second.observe("provider_queue_wait_seconds", .1, {
        "provider": "qwen", "capability": "llm", "profile": policy.fingerprint_hash,
        "priority": ProviderPriority.QUERY.name.lower(),
    })

    scraped = generate_latest(registry).decode("utf-8")
    assert "rag_provider_rejections_total" in scraped
    assert "rag_provider_queue_wait_seconds" in scraped
    for forbidden in ("api_key", "endpoint", "query=", "answer=", "user_id", "token="):
        assert forbidden not in scraped


def test_provider_metrics_use_only_bounded_allowlisted_labels():
    registry = CollectorRegistry()
    metrics = PrometheusMetrics(registry=registry)
    policy = ProviderPolicy(model="qwen-plus")
    base = {
        "provider": "qwen",
        "capability": "llm",
        "profile": policy.fingerprint_hash,
        "priority": ProviderPriority.QUERY.name.lower(),
    }
    metrics.observe("provider_call_outcomes_total", 1, {**base, "outcome": "429"})
    metrics.observe("provider_circuit_state", 1, {**base, "state": "open"})
    scraped = generate_latest(registry).decode("utf-8")
    assert "profile=\"" + policy.fingerprint_hash + "\"" in scraped
    assert "state=\"open\"" in scraped
    assert "user" not in scraped.lower()
