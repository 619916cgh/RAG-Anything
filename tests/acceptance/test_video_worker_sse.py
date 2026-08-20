"""Disposable HTTP -> Worker -> PostgreSQL -> SSE acceptance for video v2."""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import asyncpg
import pytest

BASE = os.getenv("VIDEO_ACCEPTANCE_BASE_URL", "")
FIXTURE = Path(os.getenv("VIDEO_ACCEPTANCE_FIXTURE", ""))
DATABASE_URL = os.getenv("VIDEO_ACCEPTANCE_DATABASE_URL", "")
COMPOSE = json.loads(os.getenv("VIDEO_ACCEPTANCE_COMPOSE", "[]"))
EVIDENCE_PATH = Path(os.getenv("VIDEO_ACCEPTANCE_EVIDENCE_PATH", ""))
PHASE_PATH = Path(os.getenv("VIDEO_ACCEPTANCE_PHASE_PATH", ""))
LOCAL_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|file://|/(?:app|tmp|var|home|Users|uploads)(?:[\\/]|$))", re.IGNORECASE)
pytestmark = pytest.mark.skipif(
    not (BASE and DATABASE_URL and FIXTURE.is_file() and COMPOSE and EVIDENCE_PATH and PHASE_PATH),
    reason="video acceptance environment is required",
)


def _request(path, *, method="GET", token="", body=None, headers=None, read_body=True, read_limit=None):
    request_headers = {"Authorization": f"Bearer {token}"} if token else {}
    request_headers.update(headers or {})
    with urlopen(Request(BASE + path, data=body, method=method, headers=request_headers), timeout=90) as response:
        payload = response.read(read_limit) if read_body else b""
        return response.status, dict(response.headers), payload


def _json(path, *, method="GET", token="", payload=None):
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    status, _headers, body = _request(path, method=method, token=token, body=data, headers={"Content-Type": "application/json"} if data else None)
    return status, json.loads(body.decode())


def _multipart(filename, content):
    boundary = "----raganything-video-acceptance"
    body = b"\r\n".join((f"--{boundary}".encode(), f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode(), b"Content-Type: video/mp4", b"", content, f"--{boundary}--".encode(), b""))
    return body, f"multipart/form-data; boundary={boundary}"


def _events(payload):
    return [json.loads(line[6:]) for line in payload.decode().splitlines() if line.startswith("data: ")]


def _coverage(ranges, duration_ms):
    covered, previous_end = 0, 0
    for start, stop in sorted(ranges):
        start, stop = max(0, start), min(duration_ms, stop)
        if stop > previous_end:
            covered += stop - max(start, previous_end)
            previous_end = stop
    return covered


def _fraction(value):
    if not isinstance(value, str) or not value or value == "0/0":
        return 0.0
    numerator, separator, denominator = value.partition("/")
    return float(numerator) / float(denominator) if separator and float(denominator) else float(numerator)


def _container_probe(video_path=""):
    command = "ffmpeg -version >/dev/null && ffprobe -version >/dev/null"
    if video_path:
        command += " && ffprobe -v error -show_entries format=duration:stream=codec_type,codec_name,avg_frame_rate,width,height -of json -- \"$VIDEO_ACCEPTANCE_PATH\""
    result = subprocess.run(COMPOSE + ["exec", "-T", "-e", f"VIDEO_ACCEPTANCE_PATH={video_path}", "app", "sh", "-ec", command], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, "container probe command failed"
    return json.loads(result.stdout) if video_path else {"ffmpeg": True, "ffprobe": True}


def _assert_no_local_paths(value):
    assert not LOCAL_PATH_RE.search(json.dumps(value, ensure_ascii=False)), "local path disclosed"


def _write_stage_evidence(summary):
    _assert_no_local_paths(summary)
    temp = EVIDENCE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(summary, ensure_ascii=True, sort_keys=True), encoding="utf-8")
    temp.replace(EVIDENCE_PATH)


def _record_phase(phase):
    temp = PHASE_PATH.with_suffix(".tmp")
    temp.write_text(phase, encoding="ascii")
    temp.replace(PHASE_PATH)


def test_video_worker_pg_and_sse_contract():
    _record_phase("container-probe")
    _container_probe()
    _record_phase("login")
    _, login = _json("/api/auth/login", method="POST", payload={"username": "acceptance_admin", "password": os.environ["DEFAULT_ADMIN_PASSWORD"]})
    token = login["access_token"]
    kb = f"videoacc{uuid.uuid4().hex[:12]}"
    _record_phase("kb-create")
    assert _json("/api/kb/create?" + urlencode({"kb_name": kb}), method="POST", token=token)[0] == 200
    _record_phase("upload")
    body, content_type = _multipart(FIXTURE.name, FIXTURE.read_bytes())
    status, _, reply = _request("/api/upload?" + urlencode({"kb": kb, "enable_video": "true"}), method="POST", token=token, body=body, headers={"Content-Type": content_type})
    assert status == 200
    task_id = json.loads(reply.decode())["task_id"]
    task = {}
    until = time.monotonic() + 600
    _record_phase("task-poll")
    while time.monotonic() < until:
        _, listing = _json("/api/upload/tasks?" + urlencode({"kb": kb}), token=token)
        task = next((value for value in listing["tasks"] if value["task_id"] == task_id), {})
        if task.get("status") in {"completed", "failed"}:
            break
        time.sleep(2)
    assert task.get("status") == "completed", "upload task did not complete"
    _record_phase("retrieval-health")
    _, health = _json("/api/knowledge/retrieval-health?" + urlencode({"kb": kb}), token=token)
    assert not health.get("documents"), "retrieval health reported unhealthy documents"

    async def rows():
        connection = await asyncpg.connect(DATABASE_URL)
        try:
            asset = await connection.fetchrow("SELECT media_id,duration_ms,fps,has_audio,profile_version,server_path FROM video_assets WHERE kb_name=$1", kb)
            segments = await connection.fetch("SELECT segment_id,media_id,segment_index,start_ms,end_ms,chunk_id,frame_refs FROM video_segments WHERE kb_name=$1 ORDER BY segment_index", kb)
            return asset, segments
        finally:
            await connection.close()

    asset, segments = asyncio.run(rows())
    _record_phase("storage-probe")
    assert asset and asset["duration_ms"] > 0 and asset["fps"] > 0 and asset["profile_version"] == "v2", "video asset metadata invalid"
    probe = _container_probe(str(asset["server_path"]))
    streams = probe.get("streams") if isinstance(probe, dict) else None
    assert isinstance(streams, list), "ffprobe stream metadata missing"
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    duration_seconds = float((probe.get("format") or {}).get("duration") or 0)
    probe_fps = _fraction((video_stream or {}).get("avg_frame_rate"))
    assert video_stream and video_stream.get("codec_name") and int(video_stream.get("width") or 0) > 0 and int(video_stream.get("height") or 0) > 0, "ffprobe video metadata invalid"
    assert duration_seconds > 0 and probe_fps > 0, "ffprobe duration or fps invalid"
    assert abs(int(round(duration_seconds * 1000)) - int(asset["duration_ms"])) <= 1_000, "probe and asset duration differ"
    assert abs(probe_fps - float(asset["fps"])) <= 0.1, "probe and asset fps differ"
    assert bool(audio_stream) is bool(asset["has_audio"]), "probe and asset audio presence differ"

    _record_phase("segment-validation")
    assert len(segments) > 1, "fixture did not produce multiple semantic segments"
    indexes = [int(row["segment_index"]) for row in segments]
    assert indexes == list(range(len(segments))), "segment indexes are not strictly ordered"
    ranges = [(int(row["start_ms"]), int(row["end_ms"])) for row in segments]
    duration_ms = int(asset["duration_ms"])
    assert ranges[0][0] == 0 and all(0 <= start < end <= duration_ms for start, end in ranges), "segment ranges are out of asset bounds"
    assert all(next_start < previous_end for (_, previous_end), (next_start, _) in zip(ranges, ranges[1:])), "adjacent segments do not overlap"
    assert _coverage(ranges, duration_ms) >= int(duration_ms * 0.99), "segment coverage is below 99 percent"
    assert all(row["media_id"] == asset["media_id"] and row["chunk_id"] and row["frame_refs"] for row in segments), "segment storage metadata invalid"
    range_by_segment = {(str(row["segment_id"]), int(row["start_ms"]), int(row["end_ms"])) for row in segments}

    _record_phase("agent-create")
    _, created = _json("/api/agents", method="POST", token=token, payload={"name": "video acceptance", "kb_name": kb, "query_mode": "hybrid", "agent_mode": "none", "include_references": True})
    agent_id = created["agent"]["id"]
    citation = None
    _record_phase("sse")
    for question in ("如何检查腐蚀漏液", "观察孔黑白代表什么", "端子为什么要按5 Nm紧固", "SVW2606如何核对"):
        status, _, stream = _request(f"/api/agents/{agent_id}/query/stream", method="POST", token=token, body=json.dumps({"query": question}).encode(), headers={"Content-Type": "application/json", "Accept": "text/event-stream"})
        assert status == 200
        events = _events(stream)
        assert any(event.get("type") == "accepted" for event in events), "SSE accepted event missing"
        done = next((event for event in events if event.get("type") == "done"), None)
        assert done and isinstance(done.get("citations"), list), "SSE done citations missing"
        citation = next((item for item in done["citations"] if item.get("media_kb") == kb), None)
        assert citation and citation.get("media_id") == asset["media_id"], "citation asset mismatch"
        anchor = citation.get("video_segment")
        assert isinstance(anchor, dict) and (anchor.get("segment_id"), anchor.get("start_ms"), anchor.get("end_ms")) in range_by_segment, "citation time range mismatch"
        assert isinstance(citation.get("media_url"), str) and citation["media_url"].startswith("/api/knowledge/media/"), "citation media URL invalid"
        _assert_no_local_paths({"events": events, "citation": citation})

    _record_phase("media-range")
    status, headers, body = _request(
        citation["media_url"], token=token, headers={"Range": "bytes=0-31"}, read_limit=32,
    )
    assert status == 206 and "Content-Range" in headers and len(body) == 32, "authorized media range request failed"
    intruder_name, intruder_password = f"video_reader_{uuid.uuid4().hex[:12]}", "VideoReader!2026"
    _record_phase("ungranted-user")
    assert _json("/api/admin/users", method="POST", token=token, payload={"username": intruder_name, "password": intruder_password})[0] == 201
    _, intruder_login = _json("/api/auth/login", method="POST", payload={"username": intruder_name, "password": intruder_password})
    intruder_token = intruder_login["access_token"]
    for path, payload in ((citation["media_url"], None), (f"/api/agents/{agent_id}/query/stream", {"query": "如何检查腐蚀漏液"})):
        with pytest.raises(HTTPError) as denied:
            _request(path, method="POST" if payload else "GET", token=intruder_token, body=json.dumps(payload).encode() if payload else None, headers={"Content-Type": "application/json", "Accept": "text/event-stream"} if payload else None)
        assert denied.value.code in {401, 403}, "ungranted user was not denied"
        _assert_no_local_paths(denied.value.read().decode(errors="replace"))

    _record_phase("evidence-write")
    _write_stage_evidence({
        "schema_version": 1,
        "video": {
            "probe": {"ffmpeg": True, "ffprobe": True, "duration_ms": int(round(duration_seconds * 1000)), "fps": probe_fps, "width": int(video_stream["width"]), "height": int(video_stream["height"]), "video_codec": str(video_stream["codec_name"]), "has_audio": bool(audio_stream), "audio_codec": str(audio_stream.get("codec_name") or "") if audio_stream else ""},
            "asset": {"media_id": str(asset["media_id"]), "duration_ms": duration_ms, "fps": float(asset["fps"]), "has_audio": bool(asset["has_audio"]), "profile_version": str(asset["profile_version"])},
            "segment_count": len(segments),
            "time_ranges": [{"index": int(row["segment_index"]), "start_ms": int(row["start_ms"]), "end_ms": int(row["end_ms"])} for row in segments],
        },
    })
