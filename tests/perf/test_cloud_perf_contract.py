from pathlib import Path

import hashlib

import pytest

from scripts.cloud_perf_manifest import (
    assert_ownership,
    assert_temp_child,
    summarize_cpu_profile,
)


ROOT = Path(__file__).parents[2]


def test_cloud_runner_is_manifest_owned_and_never_uses_global_prune():
    content = (ROOT / "scripts" / "run_isolated_cloud_perf.sh").read_text(encoding="utf-8")
    assert "PERF_APP_IMAGE is required" in content
    assert "docker image inspect" in content
    assert "image_digest" in content
    assert "resolve_image_id" in content
    assert "app_image_id" in content
    assert "write_production_probe" in content
    assert "wait_for_test_ready" in content
    assert "copy_sanitized_report" in content
    assert "metrics_url" in content
    assert "PERF_RATE_LIMIT_MODE" in content
    assert "PERF_CPU_PROFILING" in content
    assert "PERF_SSE_PHASE_ATTRIBUTION" in content
    assert "--read-only" in content
    assert "--network none" in content
    assert "--tmpfs /app/workflows:rw,nosuid,size=1m" in content
    assert "LOG_DIR=/tmp/logs" in content
    assert "WORKING_DIR=/tmp/rag_storage" in content
    assert "RUNTIME_SETTINGS_FILE=/tmp/runtime_settings.json" in content
    assert "PERF_DIAGNOSTIC_MODE" in content
    assert "PERF_DIAGNOSTIC_AUTHORIZATION" in content
    assert "authorized-30-40-50-ladder" in content
    assert "PERF_DIAGNOSTIC_STAGE must be 30, 40, or 50" in content
    assert "PERF_RESOURCE_PROFILE" in content
    assert "PERF_PROFILE_B_STAGE" in content
    assert "profile-b-4cpu-6g-ladder" in content
    assert "validate_profile_b_predecessor" in content
    assert "cpu_stop_percent=170" in content
    assert "cpu_emergency_percent=190" in content
    assert "owned_app_container" in content
    assert "X-Raganything-Perf-Profile" in content
    assert "/api/internal/perf/cpu-profile/start" in content
    assert "/api/internal/perf/cpu-profile/stop" in content
    assert "summarize-cpu-profile" in content
    assert "profiler_output_invalid" in content
    assert 'docker exec "$app_container" rm -f /tmp/raganything-perf-cpu.pstats' in content
    assert "raganything.perf.run-id" in content
    assert "assert_owned_resources" in content
    assert "record_owned_resources" in content
    assert "assert_owned_resources_removed" in content
    assert "owned_resources_are_absent" in content
    assert "docker volume inspect" in content
    assert "docker network inspect" in content
    assert "docker system prune" not in content
    assert "env_file" not in content
    assert "deploy.config.psd1" not in content
    assert "127.0.0.1" in content
    assert "http://127.0.0.1/api/live" in content
    assert "http://127.0.0.1/api/ready" in content
    assert "host_ip: 127.0.0.1" in content
    assert "{{if .State.Health}}" in content
    assert "for container in raganything-app raganything-marker; do" in content
    assert "/app/server.py:ro" not in content


def test_cloud_runner_cleanup_probe_manifest_block_is_valid_python():
    content = (ROOT / "scripts" / "run_isolated_cloud_perf.sh").read_text(encoding="utf-8")
    command = 'python3 - "$run_dir/manifest.json" "$run_dir/production-before.json" "$run_dir/production-after.json"'
    block = content[content.index(command):].split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
    compile(block, "cleanup-production-probes", "exec")


def test_cloud_compose_is_fixed_image_full_stack_with_owned_storage():
    content = (ROOT / "tests" / "perf" / "compose.cloud.perf.yml").read_text(encoding="utf-8")
    for service in ("mock-provider:", "postgres:", "redis:", "migrate:", "app:", "marker:", "nginx:"):
        assert service in content
    assert "build:" not in content
    assert "container_name:" not in content
    assert "env_file:" not in content
    assert 'ports: ["127.0.0.1:${PERF_HTTP_PORT:?generated port required}:80"]' in content
    assert "/app/server.py" not in content
    assert "/app/raganything/runtime_metrics.py" not in content
    assert "VISION_EMBEDDING_HOST: http://mock-provider:18000/v1" in content
    assert "http://localhost:18000/openapi.json" in content
    assert "PERF_POSTGRES_IMAGE" in content
    assert "PERF_REDIS_IMAGE" in content
    assert "PERF_ISOLATED_RATE_LIMIT" in content
    assert "PERF_CPU_PROFILING: ${PERF_CPU_PROFILING:-0}" in content
    assert "PERF_SSE_PHASE_ATTRIBUTION: ${PERF_SSE_PHASE_ATTRIBUTION:-0}" in content
    assert "cpu-profiler:" not in content
    assert "labels: *perf_labels" in content
    assert "networks:" in content
    assert content.count("mem_limit:") >= 7
    assert content.count("pids_limit:") >= 7
    assert "PERF_APP_CPUS:-2.0" in content
    assert "PERF_APP_MEM_LIMIT:-3g" in content
    assert "MAX_ASYNC: ${PERF_APP_MAX_ASYNC:-1}" in content


def test_profile_b_identity_includes_fixed_app_concurrency_and_rejects_mixed_predecessors():
    content = (ROOT / "scripts" / "run_isolated_cloud_perf.sh").read_text(encoding="utf-8")
    assert "profile_b_max_async=4" in content
    assert "PERF_APP_MAX_ASYNC=$app_max_async" in content
    assert '"app_max_async": app_max_async' in content
    assert "profile_b_config_sha256" in content
    assert "predecessor Profile B configuration mismatch" in content


def test_direct_50_profile_b_diagnostic_is_explicit_and_non_admissible():
    runner = (ROOT / "scripts" / "run_profile_b_ladder.py").read_text(encoding="utf-8")
    shell = (ROOT / "scripts" / "run_isolated_cloud_perf.sh").read_text(encoding="utf-8")
    assert '"--direct-50-diagnostic"' in runner
    assert "direct Profile B diagnostic requires stage 50 without predecessor evidence" in runner
    assert "profile_b_direct_diagnostic_completed" in runner
    assert 'result["ordered_ladder_eligible"] = False' in runner
    assert "PERF_PROFILE_B_DIRECT_AUTHORIZATION" in shell
    assert "profile-b-8cpu-24g-direct-50" in shell
    assert "profile-b-direct-50-8cpu-24g" in shell
    assert "app_cpus=8.0" in shell
    assert "app_mem_limit=24g" in shell
    assert 'expected_limits="8000000000 25769803776"' in shell
    assert "direct Profile B diagnostic requires stage 50 without predecessor" in shell
    assert "profile_b_execution_mode" in shell
    assert "profile_b_predecessor_evidence" in shell


def test_profile_b_runner_emits_phase_progress_and_refuses_competing_isolated_stacks():
    runner = (ROOT / "scripts" / "run_profile_b_ladder.py").read_text(encoding="utf-8")
    shell = (ROOT / "scripts" / "run_isolated_cloud_perf.sh").read_text(encoding="utf-8")
    assert '"recovery_start"' in runner
    assert '"cleanup_complete"' in runner
    assert '"kind": "runner_progress"' in runner
    assert "assert_no_active_profile_b_stack" in shell
    assert "another Profile B isolated stack is still active" in shell


def test_collector_has_fixed_production_health_probes():
    content = (ROOT / "scripts" / "collect_perf_resources.py").read_text(encoding="utf-8")
    assert "def _production_health" in content
    assert '"/api/live", "/api/ready"' in content
    assert '"raganything-app", "raganything-nginx", "raganything-marker", "raganything-pg", "raganything-redis"' in content
    assert "CPU emergency threshold is outside the approved range" in content
    assert "ladder diagnostic stage is outside the approved allow-list" in content


def test_cloud_fixtures_are_fixed_non_ocr_inputs():
    fixtures = ROOT / "tests" / "perf" / "fixtures"
    text = fixtures / "sample.txt"
    pdf = fixtures / "cloud_fixture.pdf"
    assert text.read_text(encoding="utf-8").startswith("RAG-Anything performance fixture")
    assert pdf.read_bytes().startswith(b"%PDF-1.4")
    assert len(pdf.read_bytes()) < 16 * 1024
    assert hashlib.sha256(text.read_bytes()).hexdigest() == "35c814781f1b1b1dd3c33366d4cd0e4fc2b377772ebd67a1ce6f06e3331cef67"


def test_cloud_runner_input_rejection_and_manifest_cleanup_ownership(tmp_path):
    temp_root = tmp_path / "temp"
    run_dir = temp_root / "raganything-cloud-perf-owned"
    run_dir.mkdir(parents=True)
    assert assert_temp_child(str(temp_root), str(run_dir)) == run_dir.resolve()
    with pytest.raises(ValueError, match="temporary"):
        assert_temp_child(str(temp_root), str(tmp_path / "outside"))
    assert_ownership("owned-project", "run-1", "owned-project run-1")
    with pytest.raises(ValueError, match="ownership"):
        assert_ownership("owned-project", "run-1", "other-project run-1")


def test_production_rate_limit_cannot_be_overridden_by_the_cloud_profile():
    content = (ROOT / "server.py").read_text(encoding="utf-8")
    assert 'os.getenv("RAGANYTHING_ENV") == "performance"' in content
    assert 'os.getenv("PERF_ISOLATED_RATE_LIMIT") == "10000/minute"' in content
    assert 'default_limits=[_default_rate_limit]' in content


def test_capacity_image_layers_only_the_test_only_rate_limit_override():
    content = (ROOT / "tests" / "perf" / "Dockerfile.cloud-capacity-app").read_text(encoding="utf-8")
    assert "FROM ${BASE_IMAGE}" in content
    assert "PERF_ISOLATED_RATE_LIMIT" in content
    assert "Router-specific limits" in content
    assert "staged upload checks" in content
    assert "in {9, 33}" in content
    assert "query-core publish/lease ordering fix" in content
    assert "acquire_query_lease=acquire_query_lease" in content
    assert "query_lease_acquired" in content
    assert "cProfile.Profile()" in content
    assert "hmac.compare_digest" in content
    assert "_perf_sse_error_stage" in content
    assert "include_in_schema=False" in content
    assert "120/minute" in content and "10000/minute" in content


def test_query_core_leasefix_layer_is_test_only_and_does_not_mount_source():
    content = (ROOT / "tests" / "perf" / "Dockerfile.cloud-capacity-leasefix").read_text(encoding="utf-8")
    assert "FROM ${BASE_IMAGE}" in content
    assert "query-core publish/lease ordering repair" in content
    assert "acquire_query_lease=acquire_query_lease" in content
    assert "COPY" not in content


def test_cpu_profile_summary_is_content_free_and_aggregates_app_frames(tmp_path):
    import cProfile

    profiler = cProfile.Profile()
    profiler.enable()
    sum(range(100))
    profiler.disable()
    profile = tmp_path / "sample.pstats"
    profiler.dump_stats(str(profile))

    summary = summarize_cpu_profile(profile)

    assert summary["frame_count"] == 0
    assert summary["frames"] == []
