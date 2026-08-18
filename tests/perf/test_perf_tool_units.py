import json

from scripts import bootstrap_perf_run, collect_perf_resources, diagnose_perf_upload, run_perf_query_smoke


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


def test_bootstrap_env_reader_keeps_values_local(tmp_path):
    env_file = tmp_path / "compose.env"
    env_file.write_text("ONE=1\nTWO=two=parts\n", encoding="ascii")
    assert bootstrap_perf_run._read_env(env_file) == {"ONE": "1", "TWO": "two=parts"}


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


def test_upload_terminal_classifier_requires_retrieval_health():
    assert diagnose_perf_upload.classify_terminal("completed", True) == "retrieval_ready"
    assert diagnose_perf_upload.classify_terminal("completed", False) == "completed_not_retrieval_ready"
    assert diagnose_perf_upload.classify_terminal("failed", None) == "worker_terminal_failed"
    assert diagnose_perf_upload.classify_terminal("retry_wait", None) == "terminal_retry_wait"


def test_upload_diagnostic_connection_classification_is_bounded():
    error = diagnose_perf_upload.requests.ConnectionError("sensitive transport detail")
    assert diagnose_perf_upload.classify_exception("poll", error) == "connection_error_poll"
