import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import run_isolated_acceptance as acceptance


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
