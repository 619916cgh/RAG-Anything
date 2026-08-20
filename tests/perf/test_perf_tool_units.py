import json
import subprocess

from scripts import bootstrap_perf_run, collect_perf_resources, continue_profile_b_ladder, diagnose_perf_upload, run_cloud_perf_workload, run_perf_query_smoke, run_profile_b_ladder


class FakeResponse:
    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self, **_kwargs):
        yield from self._lines


def test_query_event_parser_preserves_accepted_token_and_done():
    response = FakeResponse(
        [
            'data: {"type":"accepted"}',
            "",
            ": heartbeat",
            'data: {"type":"token","content":"x"}',
            "",
            'data: {"type":"done"}',
            "",
        ]
    )
    assert [kind for kind, _payload in run_perf_query_smoke._events(response)] == [
        "accepted", "heartbeat", "token", "done"
    ]


def test_query_event_parser_marks_invalid_json():
    response = FakeResponse(["data: {invalid", ""])
    assert list(run_perf_query_smoke._events(response)) == [("malformed", {})]


def test_cloud_query_parser_uses_json_data_type_not_sse_event_field():
    response = FakeResponse([
        'data: {"type":"accepted"}', "",
        'data: {"type":"retrieval","context_present":true,"text_source_count":1}', "",
        'data: {"type":"done"}', "",
    ])
    assert [kind for kind, _payload in run_cloud_perf_workload._events(response)] == ["accepted", "retrieval", "done"]


def test_cloud_sse_failure_trace_is_content_free_and_phase_classified():
    class StreamResponse(FakeResponse):
        status_code = 200

    class StreamSession:
        def post(self, *_args, **_kwargs):
            return StreamResponse([
                'data: {"type":"accepted"}', "",
                'data: {"type":"agent_info","thread_id":"secret-thread"}', "",
                'data: {"type":"retrieval","context_present":true,"text_source_count":1}', "",
                'data: {"type":"token","content":"secret answer"}', "",
                'data: {"type":"error","code":"query_core_acquire","content":"sensitive exception detail","unexpected":"secret"}', "",
            ])

    result, next_thread = run_cloud_perf_workload._stream_query(
        StreamSession(), "http://127.0.0.1:1", {"agent_id": "secret-agent"}, "secret-token", 1,
        thread_id=None, retrieval_only=False,
    )

    assert result["error_class"] == "sse_error_query_core_acquire"
    assert result["error_phase"] == "after_token_persistence_or_terminal"
    assert result["error_code"] == "query_core_acquire"
    assert result["event_sequence"] == ["accepted", "agent_info", "retrieval", "token", "error"]
    assert result["terminal_kind"] == "error"
    assert "secret" not in json.dumps(result)
    assert next_thread == "secret-thread"


def test_cloud_sse_trace_discards_unknown_event_name_and_classifies_eof():
    assert run_cloud_perf_workload._safe_event_type("unexpected-secret-type") == "other"
    assert run_cloud_perf_workload._safe_error_code({"code": "unexpected-secret-code"}) == ""
    assert run_cloud_perf_workload._error_phase(["accepted", "agent_info", "retrieval", "error"]) == "after_retrieval_before_token"
    assert run_cloud_perf_workload._protocol_class(["accepted", "agent_info", "done"], "done") == ""
    assert run_cloud_perf_workload._protocol_class(["accepted", "done", "token"], "done") == "event_after_terminal"
    assert run_cloud_perf_workload._protocol_class(["token", "error"], "error") == "accepted_count_invalid"


def test_cloud_sse_trace_tracks_long_stream_protocol_without_retaining_it():
    class StreamResponse(FakeResponse):
        status_code = 200

    class StreamSession:
        def post(self, *_args, **_kwargs):
            lines = ['data: {"type":"accepted"}', ""]
            lines.extend(['data: {"type":"agent_info","thread_id":"thread"}', ""])
            lines.extend(['data: {"type":"token","content":"x"}', ""])
            lines.extend(item for _ in range(65) for item in ('data: {"type":"thinking"}', ""))
            lines.extend(['data: {"type":"done"}', ""])
            return StreamResponse(lines)

    result, _unused = run_cloud_perf_workload._stream_query(
        StreamSession(), "http://127.0.0.1:1", {"agent_id": "agent"}, "token", 1,
        thread_id=None, retrieval_only=False,
    )
    assert result["event_count"] == 69
    assert len(result["event_sequence"]) == 64
    assert result["event_sequence_truncated"] is True
    assert run_cloud_perf_workload._profile_b_protocol_class(result) == ""


def test_profile_b_protocol_trace_rejects_an_event_after_terminal():
    result = {
        "terminal_kind": "done",
        "protocol_trace": {
            "first_event": "accepted", "accepted_count": 1, "agent_info_seen": True,
            "token_seen": True, "terminal_count": 1, "event_after_terminal": True,
            "unknown_event_seen": False, "error_event_seen": False,
        },
    }
    assert run_cloud_perf_workload._profile_b_protocol_class(result) == "event_after_terminal"


def test_cloud_percentile_is_deterministic_and_bounded():
    assert run_cloud_perf_workload._percentile([1.0, 2.0, 3.0], 0.95) == 3.0
    assert run_cloud_perf_workload._percentile([], 0.5) is None


def test_cloud_upload_fixtures_are_unique_and_keep_the_pdf_content_type():
    text_name, text_body, text_type = run_cloud_perf_workload._fixture_bytes("text", "run-1", 1, 1)
    pdf_name, pdf_body, pdf_type = run_cloud_perf_workload._fixture_bytes("pdf", "run-1", 1, 1)
    assert text_name.endswith(".txt") and b"run=run-1" in text_body and text_type == "text/plain"
    assert pdf_name.endswith(".pdf") and pdf_body.startswith(b"%PDF-1.4") and pdf_type == "application/pdf"


def test_cloud_upload_fixture_sequence_accepts_a_stage_specific_value():
    first = run_cloud_perf_workload._fixture_bytes("text", "run-1", 1, "diagnostic-1")
    second = run_cloud_perf_workload._fixture_bytes("text", "run-1", 1, "stage-3-1")
    assert first[0] != second[0]
    assert first[1] != second[1]


def test_bootstrap_env_reader_keeps_values_local(tmp_path):
    env_file = tmp_path / "compose.env"
    env_file.write_text("ONE=1\nTWO=two=parts\n", encoding="ascii")
    assert bootstrap_perf_run._read_env(env_file) == {"ONE": "1", "TWO": "two=parts"}


def test_bootstrap_workload_names_are_distinct_and_bounded():
    first = bootstrap_perf_run._workload_name("run-12345678", 0)
    second = bootstrap_perf_run._workload_name("run-12345678", 1)
    assert first != second
    assert first.startswith("12345678000")
    assert second.startswith("12345678001")


def test_collector_rejects_non_loopback_metrics_without_network_access():
    assert collect_perf_resources._metrics("https://example.invalid/metrics") == {
        "available": False,
        "error_class": "unsafe_metrics_url",
    }


def test_collector_marks_missing_service_and_invalid_stats_unavailable():
    assert collect_perf_resources._exec(None, "true") == {
        "available": False,
        "error_class": "service_not_found",
    }
    assert collect_perf_resources._parse_stats("not-json") == {
        "available": False,
        "error_class": "invalid_docker_stats",
    }


def test_collector_host_observation_is_structured_when_available():
    result = collect_perf_resources._host_resources()
    if result["available"]:
        assert result["memory_available_bytes"] > 0
        assert result["disk_free_bytes"] > 0
    else:
        assert result["error_class"]


def test_collector_stops_only_after_three_resource_samples_and_on_restart():
    stats = {"CPUPerc": "86.00%", "MemUsage": "10MiB / 100MiB"}
    assert collect_perf_resources._breach_reason(stats, "oom=false restart=0", previous=0) == (None, 1)
    assert collect_perf_resources._breach_reason(stats, "oom=false restart=0", previous=2)[0] == "owned_container_cpu_or_rss_threshold"
    assert collect_perf_resources._breach_reason({}, "oom=true restart=0", previous=0)[0] == "owned_container_restart_or_oom"


def test_collector_authorized_diagnostic_cpu_gate_is_bounded():
    stats = {"CPUPerc": "171.00%", "MemUsage": "10MiB / 3GiB"}
    assert collect_perf_resources._breach_reason(
        stats, "oom=false restart=0", previous=0, cpu_stop_percent=170, cpu_emergency_percent=190
    ) == (None, 1)
    assert collect_perf_resources._breach_reason(
        stats, "oom=false restart=0", previous=2, cpu_stop_percent=170, cpu_emergency_percent=190
    )[0] == "owned_container_cpu_or_rss_threshold"
    emergency = {"CPUPerc": "190.00%", "MemUsage": "10MiB / 3GiB"}
    assert collect_perf_resources._breach_reason(
        emergency, "oom=false restart=0", previous=0, cpu_stop_percent=170, cpu_emergency_percent=190
    )[0] == "owned_container_cpu_emergency_threshold"


def test_profile_b_normalizes_app_cpu_and_keeps_cpu_rss_counters_separate():
    stats = {"CPUPerc": "300.00%", "MemUsage": "1GiB / 6GiB"}
    reason, cpu, rss, normalized = collect_perf_resources._profile_b_breach_reason(
        stats, "oom=false restart=0", previous_cpu=0, previous_rss=0,
        cpu_quota=4.0, memory_quota_bytes=6 * 1024**3,
    )
    assert reason is None and cpu == 0 and rss == 0
    assert normalized["cpu_percent_of_quota"] == 75.0
    emergency, _cpu, _rss, _normalized = collect_perf_resources._profile_b_breach_reason(
        {"CPUPerc": "360.00%", "MemUsage": "1GiB / 6GiB"}, "oom=false restart=0",
        previous_cpu=0, previous_rss=0, cpu_quota=4.0, memory_quota_bytes=6 * 1024**3,
    )
    assert emergency == "profile_b_app_cpu_emergency"


def test_profile_b_summary_requires_every_request_terminal_latency_and_trace():
    valid = {
        "outcome": "success", "terminal_kind": "done", "event_sequence": ["accepted", "agent_info", "retrieval", "token", "done"],
        "event_sequence_truncated": False, "protocol_class": "", "retrieval_context_present": False,
        "retrieval_source_count": 0, "ttft_ms": 2100, "total_ms": 2700, "retry_count": 0,
    }
    assert run_cloud_perf_workload._profile_b_summary([valid], stopped=False)["passed"] is True
    failed = dict(valid, outcome="failed")
    assert run_cloud_perf_workload._profile_b_summary([failed], stopped=False)["passed"] is False
    slow = dict(valid, ttft_ms=2101)
    assert run_cloud_perf_workload._profile_b_summary([slow], stopped=False)["passed"] is False


def test_profile_b_summary_reports_only_aggregate_timing_and_protocol_categories():
    invalid = {
        "outcome": "success", "terminal_kind": "done", "event_sequence": ["accepted", "agent_info", "done"],
        "event_sequence_truncated": False, "protocol_class": "", "ttfb_ms": 100,
        "ttft_ms": 1000, "total_ms": 2000, "retry_count": 0,
    }
    summary = run_cloud_perf_workload._profile_b_summary([invalid], stopped=False)
    assert summary["timing_ms"]["ttfb_ms"]["p95"] == 100
    assert summary["protocol_failure_classes"] == {"required_event_missing": 1}
    assert summary["latency_gates_ms"] == {"ttft_p95_max": 2100, "total_p95_max": 2700}


def test_query_breach_accepts_successful_rows_without_ambient_policy_state(tmp_path):
    (tmp_path / "query-stage.ndjson").write_text(
        json.dumps({"outcome": "success", "error_class": "", "rate_limit_mode": "capacity"}) + "\n",
        encoding="utf-8",
    )
    assert collect_perf_resources._query_breach(tmp_path) is None


def test_query_breach_stops_any_non_success_for_diagnostic_stages(tmp_path):
    (tmp_path / "query-stage.ndjson").write_text(
        json.dumps({"outcome": "failed", "error_class": "sse_error", "rate_limit_mode": "capacity"}) + "\n",
        encoding="utf-8",
    )
    assert collect_perf_resources._query_breach(tmp_path) == "query_non_success"


def test_collector_writes_incremental_samples_before_the_run_finishes():
    content = (collect_perf_resources.Path(__file__).parents[2] / "scripts" / "collect_perf_resources.py").read_text(encoding="utf-8")
    assert 'output.open("a", encoding="utf-8")' in content


def test_recovery_mode_records_only_redacted_time_samples():
    content = (run_cloud_perf_workload.Path(__file__).parents[2] / "scripts" / "run_cloud_perf_workload.py").read_text(encoding="utf-8")
    assert '"kind": "recovery_sample"' in content
    assert 'choices=("readiness", "query", "upload-diagnostic", "upload-stage", "recovery")' in content


def test_upload_terminal_classifier_requires_retrieval_health():
    assert diagnose_perf_upload.classify_terminal("completed", True) == "retrieval_ready"
    assert diagnose_perf_upload.classify_terminal("completed", False) == "completed_not_retrieval_ready"
    assert diagnose_perf_upload.classify_terminal("failed", None) == "worker_terminal_failed"
    assert diagnose_perf_upload.classify_terminal("retry_wait", None) == "terminal_retry_wait"


def test_upload_diagnostic_connection_classification_is_bounded():
    error = diagnose_perf_upload.requests.ConnectionError("sensitive transport detail")
    assert diagnose_perf_upload.classify_exception("poll", error) == "connection_error_poll"


def test_profile_b_runner_failure_evidence_is_step_scoped_and_content_free():
    failure = run_profile_b_ladder.RunnerStageError(
        "readiness",
        subprocess.CalledProcessError(1, ["sensitive-command", "secret-value"]),
    )
    result = run_profile_b_ladder._failure_classification(failure)
    assert result == {"failure_step": "readiness", "failure_class": "subprocess_failed"}
    assert "secret" not in json.dumps(result)


def test_profile_b_preflight_is_bounded():
    content = (run_profile_b_ladder.Path(__file__).parents[2] / "scripts" / "run_profile_b_ladder.py").read_text(encoding="utf-8")
    assert 'str(runner), "preflight"], environment, timeout=60' in content
    assert '"profile-b-runner-step=preflight"' in content
    assert '"profile-b-runner-step=up"' in content
    assert "capture_output=True, timeout=240" in content


def test_profile_b_progress_is_incremental_and_content_free(tmp_path):
    progress = tmp_path / "runner-progress.ndjson"
    run_profile_b_ladder._write_progress(progress, "query_start")
    row = json.loads(progress.read_text(encoding="utf-8"))
    assert row["kind"] == "runner_progress"
    assert row["phase"] == "query_start"
    assert set(row) == {"kind", "phase", "timestamp"}


def test_profile_b_result_keeps_only_aggregate_timing_diagnostics():
    recovery_rows = [
        {"kind": "host"} for _ in range(run_profile_b_ladder.RECOVERY_SAMPLES)
    ] + [
        {"kind": "production_health", "result": {"healthy": True}}
        for _ in range(run_profile_b_ladder.RECOVERY_SAMPLES)
    ] + [{"kind": "collection_summary", "samples": run_profile_b_ladder.RECOVERY_SAMPLES, "stop_reason": ""}]
    result = run_profile_b_ladder._profile_b_result(
        {
            "profile_b": {
                "passed": False,
                "requests": 2,
                "successes": 2,
                "ttft_p95_ms": 1600,
                "total_p95_ms": 2600,
                "timing_ms": {
                    "ttfb_ms": {"p50": 100, "p95": 200, "p99": 300},
                    "ttft_ms": {"p50": 1200, "p95": 1600, "p99": 1800},
                    "total_ms": {"p50": 2200, "p95": 2600, "p99": 2900},
                },
                "retries": 0,
                "protocol_failures": 0,
                "stopped": False,
            }
        },
        recovery_rows,
    )
    assert result["timing_ms"]["ttfb_ms"]["p99"] == 300
    assert result["retries"] == 0
    assert result["protocol_failures"] == 0
    assert result["recovery_passed"] is True
    assert result["recovery_failure_class"] == ""


def test_profile_b_recovery_classifies_collector_failure_without_overwriting_query_gate():
    rows = [
        {"kind": "host"} for _ in range(run_profile_b_ladder.RECOVERY_SAMPLES)
    ] + [
        {"kind": "production_health", "result": {"healthy": True}}
        for _ in range(run_profile_b_ladder.RECOVERY_SAMPLES)
    ] + [{"kind": "collection_summary", "samples": run_profile_b_ladder.RECOVERY_SAMPLES, "stop_reason": ""}]
    result = run_profile_b_ladder._profile_b_result(
        {"profile_b": {"passed": False, "requests": 1, "successes": 1}},
        rows,
        recovery_returncode=2,
    )
    assert result["classification"] == "profile_b_hard_stop"
    assert result["recovery_passed"] is False
    assert result["recovery_failure_class"] == "recovery_collector_process_failed"
    assert "command" not in json.dumps(result)


def test_profile_b_recovery_requires_complete_healthy_evidence():
    rows = [
        {"kind": "host"} for _ in range(run_profile_b_ladder.RECOVERY_SAMPLES)
    ] + [
        {"kind": "production_health", "result": {"healthy": True}}
        for _ in range(run_profile_b_ladder.RECOVERY_SAMPLES)
    ] + [{"kind": "collection_summary", "samples": run_profile_b_ladder.RECOVERY_SAMPLES, "stop_reason": ""}]
    assert run_profile_b_ladder._recovery_outcome(rows, 0) == (True, "", "")
    assert run_profile_b_ladder._recovery_outcome(rows[:-1], 0) == (False, "recovery_evidence_incomplete", "")
    stopped = rows + [{"kind": "stop", "reason": "profile_b_app_cpu_emergency"}]
    assert run_profile_b_ladder._recovery_outcome(stopped, 0) == (
        False, "recovery_resource_stop", "profile_b_app_cpu_emergency"
    )
    unhealthy = list(rows)
    unhealthy[run_profile_b_ladder.RECOVERY_SAMPLES] = {"kind": "production_health", "result": {"healthy": False}}
    assert run_profile_b_ladder._recovery_outcome(unhealthy, 0) == (
        False, "recovery_production_health_unhealthy", ""
    )


def test_direct_50_diagnostic_has_a_distinct_non_admissible_classification():
    assert run_profile_b_ladder._direct_50_classification({"classification": "profile_b_stage_passed"}) == (
        "profile_b_direct_diagnostic_completed"
    )
    assert run_profile_b_ladder._direct_50_classification({"classification": "profile_b_hard_stop"}) == (
        "profile_b_direct_diagnostic_hard_stop"
    )


def test_profile_b_continuation_requires_the_exact_passing_predecessor(tmp_path):
    report = tmp_path / "ten.json"
    report.write_text(json.dumps({
        "resource_profile": "profile-b",
        "profile_b_execution_mode": "ordered-ladder",
        "profile_b_stage": 10,
        "cleanup_verified": True,
        "profile_b_result": {"classification": "profile_b_stage_passed", "recovery_passed": True},
    }), encoding="utf-8")
    assert continue_profile_b_ladder._passed_report(report, 10) is True
    assert continue_profile_b_ladder._passed_report(report, 20) is False
    assert continue_profile_b_ladder.STAGES == (5, 10, 20, 30, 40, 50)
    direct = tmp_path / "direct.json"
    direct.write_text(json.dumps({
        "resource_profile": "profile-b",
        "profile_b_execution_mode": "direct-50-diagnostic",
        "profile_b_stage": 50,
        "cleanup_verified": True,
        "profile_b_result": {"classification": "profile_b_stage_passed", "recovery_passed": True},
    }), encoding="utf-8")
    assert continue_profile_b_ladder._passed_report(direct, 50) is False
