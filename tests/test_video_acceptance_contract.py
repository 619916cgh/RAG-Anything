import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import run_isolated_acceptance as acceptance


def test_upload_progress_locator_contract_is_scoped_and_classified_as_harness_owned():
    source = (Path(__file__).parent / "acceptance" / "video_browser_uat.mjs").read_text(encoding="utf-8")
    assert "async function waitForUploadProgress(page, filename)" in source
    assert "#server-upload-tasks" in source
    assert "taskRows = taskContainer.locator(':scope > div').filter({ has: page.getByText(filename, { exact: true }) })" in source
    for field in ("upload_progress_locator_match_count", "upload_progress_locator_scope", "upload_progress_locator_resolution"):
        assert field in source
    for resolution in ("progress-text-exact", "status-text-exact", "multiple-task-rows", "multiple-progress-or-status", "no-task-row", "no-progress-or-status"):
        assert resolution in source
    assert "phaseAFailureClass(error)" in source
    assert "await page.getByText(/排队中|处理中|入库中|进度 [1-9]\\d?%/).waitFor" not in source


def test_upload_batch_status_is_retained_when_upload_progress_harness_fails():
    source = (Path(__file__).parent / "acceptance" / "video_browser_uat.mjs").read_text(encoding="utf-8")
    assert "upload_batch_status: 0" in source
    assert "phaseAEvidence?.observations) phaseAEvidence.observations.upload_batch_status = boundedCount(batchResponse.status())" in source
    assert "upload_progress_locator_multiple_match" in source


def test_upload_diagnosis_is_single_upload_and_redacted_state_contract():
    source = (Path(__file__).parent / "acceptance" / "video_browser_uat.mjs").read_text(encoding="utf-8")
    assert "VIDEO_BROWSER_UPLOAD_DIAGNOSIS" in source
    assert "waitForTerminal = true" in source
    assert "waitForTerminal: false" in source
    for field in (
        "task_status_timeline", "task_reason_class", "worker_consumed",
        "document_status", "document_chunks_count", "retrieval_unready_reason_count",
        "video_segments_http_status", "video_segment_count",
        "task_id_present", "document_id_present", "document_id_candidate_present", "task_document_mapping",
        "task_document_mapping_match", "task_document_mapping_source",
        "mapping_failure_reason_class",
    ):
        assert field in source
    assert "schema_version: 2" in source
    assert "document?.full_id" in source
    assert "document.upload_task_id" in source
    assert "document.track_id" in source
    assert "document.metadata.task_id" in source
    assert "task_provenance_not_found" in source
    assert "task_document_provenance_unavailable" in source
    assert "createAgent(page" not in source[source.index("async function runUploadDiagnosis"):source.index("async function runPhaseARepresentative")]
    assert "threadId" not in source[source.index("async function runUploadDiagnosis"):source.index("async function runPhaseARepresentative")]


def test_upload_diagnosis_mapping_does_not_fall_back_to_first_or_filename_match():
    source = (Path(__file__).parent / "acceptance" / "video_browser_uat.mjs").read_text(encoding="utf-8")
    diagnosis = source[source.index("async function runUploadDiagnosis"):source.index("async function runPhaseARepresentative")]
    assert "documentList[0]" not in diagnosis
    assert ".find(item => String(item?.upload_task_id || '') === taskId)" not in diagnosis
    assert "filename ===" not in diagnosis
    assert "file ===" not in diagnosis


def test_upload_diagnosis_loader_rejects_inconsistent_mapping(tmp_path):
    from scripts.run_isolated_acceptance import _load_upload_diagnosis_evidence

    payload = {
        "schema_version": 2,
        "upload_diagnosis": True,
        "upload_batch_status": 200,
        "upload_progress": True,
        "upload_terminal": False,
        "observations": {
            "task_http_status": 200,
            "task_count": 1,
            "task_status": "completed",
            "task_status_timeline": [],
            "task_reason_class": "none",
            "worker_consumed": True,
            "task_id_present": True,
            "document_id_present": False,
            "document_id_candidate_present": False,
            "task_document_mapping": "matched",
            "task_document_mapping_match": False,
            "task_document_mapping_source": "none",
            "mapping_failure_reason_class": "none",
            "document_http_status": 200,
            "document_count": 0,
            "document_status": "not_found",
            "retrieval_http_status": 200,
            "retrieval_ready": False,
            "video_segments_http_status": 0,
            "video_segment_count": 0,
        },
    }
    path = tmp_path / "browser-stage-evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="mapping match is inconsistent"):
        _load_upload_diagnosis_evidence(path)


def test_upload_diagnosis_runner_mode_is_isolated_and_non_phase_a():
    source = (Path(__file__).parent.parent / "scripts" / "run_isolated_acceptance.py").read_text(encoding="utf-8")
    compose = (Path(__file__).parent / "acceptance" / "compose.yml").read_text(encoding="utf-8")
    assert "--upload-diagnosis" in source
    assert "VIDEO_BROWSER_UPLOAD_DIAGNOSIS" in source
    assert 'result["release_recommendation"] = "upload-diagnosis-pass"' in source
    assert 'VIDEO_BROWSER_UPLOAD_DIAGNOSIS: ${VIDEO_BROWSER_UPLOAD_DIAGNOSIS:-0}' in compose
    assert "_load_upload_diagnosis_evidence" in source
    assert "_write_diagnosis_command_output" in source
    assert 'payload.get("schema_version") != 2' in source
    assert '"task_document_mapping"' in source


def test_video_fixture_requires_absolute_nonempty_mp4(tmp_path):
    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"video")
    workdir = tmp_path / "stage"
    workdir.mkdir()
    staged = acceptance._stage_video_fixture(source.resolve(), workdir)
    assert staged.name == "video-fixture.mp4"
    assert staged.read_bytes() == b"video"
    with pytest.raises(ValueError):
        acceptance._stage_video_fixture(Path("lesson.mp4"), tmp_path)
    with pytest.raises(ValueError):
        acceptance._stage_video_fixture(tmp_path / "lesson.txt", tmp_path)


def test_video_mock_contains_all_battery_terms():
    from tests.acceptance import mock_video_provider

    assert all(term in mock_video_provider.SUMMARY for term in mock_video_provider.TERMS)
    assert mock_video_provider._embedding("检查腐蚀漏液")[0] == 1.0
    assert mock_video_provider.MultimodalEmbeddingRequest.model_fields["dimensions"].default is None


def test_video_stage_evidence_is_whitelisted_and_path_free(tmp_path):
    stage = tmp_path / "video-stage-evidence.json"
    payload = {
        "schema_version": 1,
        "video": {
            "probe": {"ffmpeg": True, "ffprobe": True, "duration_ms": 48_000, "fps": 25.0, "width": 1920, "height": 1080, "video_codec": "h264", "has_audio": True, "audio_codec": "aac"},
            "asset": {"media_id": "media-1", "duration_ms": 48_000, "fps": 25.0, "has_audio": True, "profile_version": "v2"},
            "segment_count": 2,
            "time_ranges": [{"index": 0, "start_ms": 0, "end_ms": 27_000}, {"index": 1, "start_ms": 24_000, "end_ms": 48_000}],
        },
    }
    stage.write_text(json.dumps(payload), encoding="utf-8")
    merged = acceptance._load_video_stage_evidence(stage)
    assert merged["segment_count"] == 2
    assert merged["time_ranges"][1]["start_ms"] == 24_000

    payload["video"]["asset"]["media_id"] = "C:\\private\\lesson.mp4"
    stage.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        acceptance._load_video_stage_evidence(stage)


def test_health_wait_retries_startup_http_errors():
    calls = []

    def urlopen(_url, timeout):
        calls.append((_url, timeout))
        if len(calls) == 1:
            raise OSError("not ready")

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        return Response()

    with patch.object(acceptance.urllib.request, "urlopen", side_effect=urlopen), patch.object(acceptance.time, "sleep"):
        acceptance._wait_for_health("http://acceptance", timeout=2)

    assert len(calls) == 4


def test_acceptance_proxy_allows_a_real_video_fixture():
    nginx_config = (Path(__file__).parent / "acceptance" / "nginx.conf").read_text(encoding="utf-8")
    assert "client_max_body_size 256m;" in nginx_config
    assert "proxy_buffering off;" in nginx_config


def test_acceptance_compose_uses_the_local_vision_embedding_mock():
    compose = (Path(__file__).parent / "acceptance" / "compose.yml").read_text(encoding="utf-8")
    assert "VISION_EMBEDDING_HOST: http://mock-provider:18000/v1" in compose
    assert 'VISION_EMBEDDING_MODEL: acceptance-mock' in compose


def test_video_failure_phase_is_allowlisted(tmp_path):
    phase = tmp_path / "video-stage-phase.txt"
    phase.write_text("upload", encoding="ascii")
    assert acceptance._load_video_failure_phase(phase) == "upload"
    phase.write_text("C:/sensitive", encoding="ascii")
    assert acceptance._load_video_failure_phase(phase) == "unknown"
