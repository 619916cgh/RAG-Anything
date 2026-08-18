"""Collect bounded, read-only observations for one manifest-owned perf run."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen


def _command(*args: str) -> dict:
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    return {
        "available": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr_class": "" if result.returncode == 0 else "command_failed",
    }


def _parse_stats(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"available": False, "error_class": "invalid_docker_stats"}


def _service_container(project: str, service: str) -> str | None:
    result = _command(
        "docker", "ps", "-q",
        "--filter", f"label=com.docker.compose.project={project}",
        "--filter", f"label=com.docker.compose.service={service}",
    )
    if not result["available"]:
        return None
    values = result["stdout"].splitlines()
    return values[0] if len(values) == 1 else None


def _exec(container: str | None, shell: str) -> dict:
    if not container:
        return {"available": False, "error_class": "service_not_found"}
    result = _command("docker", "exec", container, "sh", "-lc", shell)
    if not result["available"]:
        return {"available": False, "error_class": result["stderr_class"]}
    return {"available": True, "value": result["stdout"]}


def _metrics(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path != "/metrics":
        return {"available": False, "error_class": "unsafe_metrics_url"}
    try:
        with urlopen(url, timeout=5) as response:
            body = response.read(2 * 1024 * 1024 + 1)
            if len(body) > 2 * 1024 * 1024:
                return {"available": False, "error_class": "metrics_too_large"}
            if response.status != 200:
                return {"available": False, "error_class": f"metrics_http_{response.status}"}
        text = body.decode("utf-8", errors="replace")
        return {
            "available": True,
            "bytes": len(body),
            "query_phase_histogram": "rag_agent_query_phase_duration_seconds" in text,
        }
    except Exception as exc:
        return {"available": False, "error_class": type(exc).__name__}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--interval", type=float, default=5)
    args = parser.parse_args()
    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_dir = manifest_path.parent
    output = Path(args.output).resolve()
    if output.parent != run_dir:
        raise ValueError("collector output must remain in the manifest run directory")
    project = str(manifest["project"])
    expected_run = str(manifest["run_id"])
    metrics_url = str(manifest["metrics_url"])
    rows: list[dict] = []
    for sample_index in range(args.samples):
        timestamp = time.time()
        containers = _command("docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}")
        if not containers["available"]:
            rows.append({"sample": sample_index, "timestamp": timestamp, "kind": "containers", "available": False, "error_class": containers["stderr_class"]})
        else:
            for container in containers["stdout"].splitlines():
                inspect = _command(
                    "docker",
                    "inspect",
                    container,
                    "--format",
                    "{{json .Config.Labels}} status={{.State.Status}} oom={{.State.OOMKilled}} restart={{.RestartCount}}",
                )
                if not inspect["available"] or expected_run not in inspect["stdout"]:
                    rows.append({"sample": sample_index, "timestamp": timestamp, "kind": "container", "available": False, "container": container, "error_class": "ownership_mismatch"})
                    continue
                stats = _command("docker", "stats", "--no-stream", "--format", "{{json .}}", container)
                parsed = _parse_stats(stats["stdout"]) if stats["available"] else {"available": False, "error_class": stats["stderr_class"]}
                rows.append({"sample": sample_index, "timestamp": timestamp, "kind": "container", "container": container, "available": bool(parsed.get("available", True)), "stats": parsed, "inspect": inspect["stdout"]})
        postgres = _service_container(project, "postgres")
        redis = _service_container(project, "redis")
        rows.extend([
            {"sample": sample_index, "timestamp": timestamp, "kind": "postgres_connections", "result": _exec(postgres, "psql -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -Atc \"SELECT state || ':' || count(*) FROM pg_stat_activity GROUP BY state ORDER BY state\"")},
            {"sample": sample_index, "timestamp": timestamp, "kind": "postgres_activity", "result": _exec(postgres, "psql -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -Atc \"SELECT count(*) FROM pg_stat_activity WHERE state='active'\"")},
            {"sample": sample_index, "timestamp": timestamp, "kind": "postgres_lock_wait", "result": _exec(postgres, "psql -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -Atc \"SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock'\"")},
            {"sample": sample_index, "timestamp": timestamp, "kind": "upload_queue", "result": _exec(postgres, "psql -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -Atc \"SELECT COALESCE(status,'') || ':' || count(*) FROM uploaded_files GROUP BY status ORDER BY status; SELECT COALESCE(EXTRACT(EPOCH FROM NOW()-MIN(created_at))::bigint,-1) FROM uploaded_files WHERE status NOT IN ('completed','failed','deleted')\"")},
            {"sample": sample_index, "timestamp": timestamp, "kind": "redis", "result": _exec(redis, "redis-cli INFO memory stats")},
            {"sample": sample_index, "timestamp": timestamp, "kind": "metrics", "result": _metrics(metrics_url)},
        ])
        if sample_index + 1 < args.samples:
            time.sleep(args.interval)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
