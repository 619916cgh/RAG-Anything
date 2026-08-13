from types import SimpleNamespace

import pytest

from raganything.utils.media import SUPPORTED_VIDEO_EXTENSIONS, is_supported_video_file


@pytest.mark.parametrize("extension", sorted(SUPPORTED_VIDEO_EXTENSIONS))
def test_supported_video_extensions_are_case_insensitive(extension):
    assert is_supported_video_file(f"clip{extension}")
    assert is_supported_video_file(f"clip{extension.upper()}")


@pytest.mark.parametrize("filename", ["report.pdf", "photo.png", "clip.m4v", "README"])
def test_non_video_extensions_do_not_enable_video(filename):
    assert not is_supported_video_file(filename)


def test_worker_derives_v2_for_legacy_snapshot_without_video_field():
    import process_worker

    result = process_worker._automatic_video_ingestion(
        "/uploads/task_clip.MP4",
        {"chunking_strategy": "recursive"},
    )

    assert result["enable_video"] is True
    assert result["video_index_profile_version"] == "v2"


def test_worker_preserves_explicit_historical_video_setting():
    import process_worker

    snapshot = {"chunking_strategy": "recursive", "enable_video": False}
    assert process_worker._automatic_video_ingestion("clip.mp4", snapshot) is snapshot


@pytest.mark.asyncio
async def test_upload_snapshot_ignores_legacy_toggle_and_derives_video(monkeypatch):
    from raganything.routers import knowledge
    from raganything.services import user_settings

    seen = {}
    resolved = SimpleNamespace(ingestion=SimpleNamespace(enable_video=False))

    async def available(_user_id):
        return ("models", "ingestion")

    async def resolve(_user_id, *, request_overrides=None, **_kwargs):
        seen["request_overrides"] = request_overrides
        return resolved

    def override(value, **kwargs):
        seen["video_override"] = kwargs
        return value

    async def persist(task_id, user_id, value):
        seen["persisted"] = (task_id, user_id, value)

    monkeypatch.setattr(user_settings, "available_sections_for_user", available)
    monkeypatch.setattr(user_settings, "resolve_user_settings_for_task", resolve)
    monkeypatch.setattr(user_settings, "with_task_ingestion_overrides", override)
    monkeypatch.setattr(user_settings, "create_task_settings_snapshot", persist)

    await knowledge._create_upload_settings_snapshot(
        "task-video", 7, enable_video="false", video_file=True,
    )

    assert "enable_video" not in seen["request_overrides"]["ingestion"]
    assert seen["video_override"] == {"enable_video": True}
    assert seen["persisted"] == ("task-video", 7, resolved)
