import pytest

from raganything.services import kb_service, pg_kb_meta_repo


@pytest.mark.asyncio
async def test_load_kb_meta_reuses_cache_and_returns_isolated_copies(monkeypatch):
    kb_service.invalidate_kb_meta_cache()
    calls = 0

    async def fake_load():
        nonlocal calls
        calls += 1
        return {
            "course-a": {
                "name": "Course A",
                "extra": {"nested": {"value": 1}},
            }
        }

    monkeypatch.setattr(pg_kb_meta_repo, "pg_load_kb_meta", fake_load)

    first = await kb_service.load_kb_meta()
    second = await kb_service.load_kb_meta()
    first["course-a"]["extra"]["nested"]["value"] = 99

    assert calls == 1
    assert second["course-a"]["extra"]["nested"]["value"] == 1


@pytest.mark.asyncio
async def test_stale_kb_meta_cache_covers_a_transient_pg_failure(monkeypatch):
    kb_service.invalidate_kb_meta_cache()
    monkeypatch.setattr(kb_service, "KB_META_CACHE_TTL_SECONDS", 0.0)

    async def successful_load():
        return {"course-a": {"name": "Course A"}}

    monkeypatch.setattr(pg_kb_meta_repo, "pg_load_kb_meta", successful_load)
    expected = await kb_service.load_kb_meta()
    kb_service._kb_meta_cache_time -= 1.0

    async def failed_load():
        raise TimeoutError("database unavailable")

    monkeypatch.setattr(pg_kb_meta_repo, "pg_load_kb_meta", failed_load)
    stale = await kb_service.load_kb_meta()

    assert stale == expected


@pytest.mark.asyncio
async def test_invalidation_forces_a_fresh_kb_meta_read(monkeypatch):
    kb_service.invalidate_kb_meta_cache()
    value = {"course-a": {"name": "Course A"}}

    async def fake_load():
        return value

    monkeypatch.setattr(pg_kb_meta_repo, "pg_load_kb_meta", fake_load)
    assert (await kb_service.load_kb_meta())["course-a"]["name"] == "Course A"

    value = {"course-a": {"name": "Renamed Course"}}
    kb_service.invalidate_kb_meta_cache()

    assert (await kb_service.load_kb_meta())["course-a"]["name"] == "Renamed Course"
