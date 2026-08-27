"""Collect bounded, read-only observations for one manifest-owned perf run."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen


def _command(*args: str, timeout: float = 10) -> dict:
    try:
        result = subprocess.run(args, text=True, capture_output=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"available": False, "returncode": None, "stdout": "", "stderr_class": "command_timeout"}
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


def _stats_for_containers(containers: list[str]) -> dict[str, dict]:
    """Read every owned container from one Docker stats snapshot.

    Running one command per container turns a nominal five-second sampling
    interval into a much longer serial loop on a busy Docker host.
    """
    if not containers:
        return {}
    result = _command(
        "docker", "stats", "--no-stream", "--format", "{{.ID}}\t{{json .}}", *containers,
        timeout=15,
    )
    if not result["available"]:
        return {container: {"available": False, "error_class": result["stderr_class"]} for container in containers}
    parsed: dict[str, dict] = {}
    for line in result["stdout"].splitlines():
        container, separator, raw = line.partition("\t")
        if separator:
            parsed[container] = _parse_stats(raw)
    return {
        container: parsed.get(container, {"available": False, "error_class": "missing_docker_stats"})
        for container in containers
    }


def _bytes(value: str) -> int | None:
    match = re.match(r"^([0-9.]+)\s*([KMGT]?i?B)$", value.strip())
    if not match:
        return None
    amount, unit = match.groups()
    scale = {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}
    return int(float(amount) * scale[unit])


def _breach_reason(
    stats: dict,
    inspect: str,
    *,
    previous: int,
    cpu_stop_percent: float = 85.0,
    cpu_emergency_percent: float = 200.0,
) -> tuple[str | None, int]:
    """Return a threshold breach only after three matching samples."""
    if "oom=true" in inspect.lower() or re.search(r"restart=[1-9]\d*", inspect):
        return "owned_container_restart_or_oom", previous + 1
    if not stats.get("available", True):
        return None, 0
    cpu_raw = str(stats.get("CPUPerc") or "").strip().rstrip("%")
    memory_raw = str(stats.get("MemUsage") or "").partition("/")
    try:
        cpu_percent = float(cpu_raw)
        if cpu_percent >= cpu_emergency_percent:
            return "owned_container_cpu_emergency_threshold", previous + 1
        cpu_over = cpu_percent > cpu_stop_percent
    except ValueError:
        cpu_over = False
    used, _separator, limit = memory_raw
    used_bytes, limit_bytes = _bytes(used), _bytes(limit)
    memory_over = bool(used_bytes is not None and limit_bytes and used_bytes / limit_bytes > 0.80)
    count = previous + 1 if cpu_over or memory_over else 0
    if count >= 3:
        return "owned_container_cpu_or_rss_threshold", count
    return None, count


def _profile_b_breach_reason(
    stats: dict,
    inspect: str,
    *,
    previous_cpu: int,
    previous_rss: int,
    cpu_quota: float,
    memory_quota_bytes: int,
) -> tuple[str | None, int, int, dict[str, float]]:
    """Apply Profile B gates to the app quota, retaining raw and normalized data."""
    if "oom=true" in inspect.lower() or re.search(r"restart=[1-9]\d*", inspect):
        return "owned_container_restart_or_oom", previous_cpu, previous_rss, {}
    if not stats.get("available", True):
        return "owned_container_stats_unavailable", previous_cpu, previous_rss, {}
    cpu_raw = str(stats.get("CPUPerc") or "").strip().rstrip("%")
    used, _separator, _limit = str(stats.get("MemUsage") or "").partition("/")
    try:
        cpu_percent = float(cpu_raw)
        used_bytes = _bytes(used)
    except ValueError:
        return "owned_container_stats_unavailable", previous_cpu, previous_rss, {}
    if used_bytes is None or cpu_quota <= 0 or memory_quota_bytes <= 0:
        return "owned_container_stats_unavailable", previous_cpu, previous_rss, {}
    normalized = {
        "cpu_raw_percent": round(cpu_percent, 3),
        "cpu_percent_of_quota": round(cpu_percent / cpu_quota, 3),
        "rss_bytes": float(used_bytes),
        "rss_percent_of_quota": round((used_bytes / memory_quota_bytes) * 100, 3),
    }
    if normalized["cpu_percent_of_quota"] >= 90:
        return "profile_b_app_cpu_emergency", previous_cpu, previous_rss, normalized
    if normalized["rss_percent_of_quota"] >= 80:
        return "profile_b_app_rss_emergency", previous_cpu, previous_rss, normalized
    cpu_count = previous_cpu + 1 if normalized["cpu_percent_of_quota"] > 75 else 0
    rss_count = previous_rss + 1 if normalized["rss_percent_of_quota"] > 70 else 0
    if cpu_count >= 3:
        return "profile_b_app_cpu_sustained", cpu_count, rss_count, normalized
    if rss_count >= 3:
        return "profile_b_app_rss_sustained", cpu_count, rss_count, normalized
    return None, cpu_count, rss_count, normalized


def _queue_age_seconds(result: dict) -> int | None:
    if not result.get("available"):
        return None
    lines = str(result.get("value") or "").splitlines()
    for value in reversed(lines):
        try:
            return int(value)
        except ValueError:
            continue
    return None


def _query_breach(run_dir: Path) -> str | None:
    rows: list[dict] = []
    for path in run_dir.glob("query-*.ndjson"):
        try:
            rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
        except (OSError, json.JSONDecodeError):
            continue
    if not rows:
        return None
    if any(row.get("rate_limit_mode") == "capacity" and row.get("error_class") == "limiter_429" for row in rows):
        return "unexpected_capacity_mode_429"
    if any(row.get("outcome") not in {"success", "limited"} for row in rows):
        return "query_non_success"
    failures = sum(row.get("error_class") in {"timeout", "http_500", "http_502", "http_503", "http_504"} for row in rows)
    if len(rows) >= 20 and failures / len(rows) > 0.01:
        return "query_5xx_or_timeout_rate"
    return None


def _host_resources() -> dict:
    try:
        memory: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            key, value = line.split(":", 1)
            if key in {"MemAvailable", "MemTotal"}:
                memory[key] = int(value.strip().split()[0]) * 1024
        stat = os.statvfs("/tmp")
        load = os.getloadavg()
        return {
            "available": True,
            "memory_available_bytes": memory.get("MemAvailable"),
            "memory_total_bytes": memory.get("MemTotal"),
            "disk_free_bytes": stat.f_bavail * stat.f_frsize,
            "disk_total_bytes": stat.f_blocks * stat.f_frsize,
            "load_1": load[0], "load_5": load[1], "load_15": load[2],
        }
    except (OSError, ValueError) as exc:
        return {"available": False, "error_class": type(exc).__name__}


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
        selected = [
            line for line in text.splitlines()
            if line.startswith((
                "rag_agent_query_phase_duration_seconds",
                "rag_provider_active_calls",
                "rag_provider_queue_wait_seconds",
                "rag_provider_rejections_total",
                "rag_provider_call_outcomes_total",
                "rag_provider_retries_total",
                "rag_provider_call_duration_seconds",
                "rag_provider_first_token_seconds",
                "rag_provider_circuit_state",
                "http_requests_total",
                "http_request_duration_seconds",
            ))
        ]
        return {
            "available": True,
            "bytes": len(body),
            "query_phase_histogram": "rag_agent_query_phase_duration_seconds" in text,
            "provider_governance_metrics": any(line.startswith("rag_provider_") for line in selected),
            "snapshot": selected[:400],
        }
    except Exception as exc:
        return {"available": False, "error_class": type(exc).__name__}


def _production_health() -> dict:
    """Read only the fixed production container and loopback health probes."""
    containers: dict[str, dict[str, object]] = {}
    healthy = True
    for name in ("raganything-app", "raganything-nginx", "raganything-marker", "raganything-pg", "raganything-redis"):
        result = _command(
            "docker", "inspect", name,
            "--format", "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.RestartCount}}",
        )
        value = result["stdout"].split() if result["available"] else []
        containers[name] = {"available": result["available"], "status": value[0] if value else "", "health": value[1] if len(value) > 1 else "", "restart": value[2] if len(value) > 2 else ""}
        healthy = healthy and result["available"] and bool(value) and value[0] == "running" and value[-1] == "0"
    endpoints: dict[str, int] = {}
    for path in ("/api/live", "/api/ready"):
        try:
            with urlopen(f"http://127.0.0.1{path}", timeout=5) as response:
                endpoints[path] = int(response.status)
        except Exception:
            endpoints[path] = 0
        healthy = healthy and endpoints[path] == 200
    return {"available": True, "healthy": healthy, "containers": containers, "endpoints": endpoints}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--stop-file")
    args = parser.parse_args()
    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_dir = manifest_path.parent
    output = Path(args.output).resolve()
    if output.parent != run_dir:
        raise ValueError("collector output must remain in the manifest run directory")
    project = str(manifest["project"])
    expected_run = str(manifest["run_id"])
    metrics_url = str(manifest.get("metrics_url", ""))
    resource_profile = str(manifest.get("resource_profile") or "profile-a")
    diagnostic_mode = str(manifest.get("diagnostic_mode") or "standard")
    cpu_stop_percent = float(manifest.get("cpu_stop_percent", 85.0))
    cpu_emergency_percent = float(manifest.get("cpu_emergency_percent", 200.0))
    if resource_profile not in {"profile-a", "profile-b"}:
        raise ValueError("unsupported resource profile")
    if diagnostic_mode not in {"standard", "authorized-20vu", "authorized-30-40-50-ladder", "profile-b"}:
        raise ValueError("unsupported diagnostic mode")
    if resource_profile == "profile-b":
        if diagnostic_mode != "profile-b" or manifest.get("profile_b_stage") not in {1, 5, 10, 20, 30, 40, 50}:
            raise ValueError("Profile B manifest is incomplete")
        app_cpu_quota = float(manifest.get("app_cpu_quota") or 0)
        app_memory_quota_bytes = int(manifest.get("app_memory_quota_bytes") or 0)
        direct_8c32g = (
            manifest.get("profile_b_execution_mode") == "direct-50-diagnostic"
            and manifest.get("profile_b_stage") == 50
            and app_cpu_quota == 8.0
            and app_memory_quota_bytes == 24 * 1024**3
        )
        ordered_4c6g = app_cpu_quota == 4.0 and app_memory_quota_bytes == 6 * 1024**3
        if not (ordered_4c6g or direct_8c32g):
            raise ValueError("Profile B resource quota is outside the approved range")
    diagnostic_stage = manifest.get("diagnostic_stage")
    if diagnostic_mode == "authorized-30-40-50-ladder" and diagnostic_stage not in {30, 40, 50}:
        raise ValueError("ladder diagnostic stage is outside the approved allow-list")
    minimum_cpu_stop = 75.0 if resource_profile == "profile-b" else 85.0
    maximum_cpu_stop = 90.0 if resource_profile == "profile-b" else 170.0
    if not minimum_cpu_stop <= cpu_stop_percent <= maximum_cpu_stop:
        raise ValueError("CPU stop threshold is outside the approved range")
    maximum_cpu_emergency = 90.0 if resource_profile == "profile-b" else 200.0
    if not cpu_stop_percent <= cpu_emergency_percent <= maximum_cpu_emergency:
        raise ValueError("CPU emergency threshold is outside the approved range")
    stop_file = Path(args.stop_file).resolve() if args.stop_file else None
    if stop_file is not None and stop_file.parent != run_dir:
        raise ValueError("stop file must remain in the manifest run directory")
    rows: list[dict] = [{
        "kind": "resource_stop_policy",
        "resource_profile": resource_profile,
        "diagnostic_only": diagnostic_mode != "standard",
        "diagnostic_stage": diagnostic_stage,
        "cpu_sustained_percent": cpu_stop_percent,
        "cpu_emergency_percent": cpu_emergency_percent,
        "required_consecutive_samples": 3,
        "rss_percent": 70.0 if resource_profile == "profile-b" else 80.0,
    }]
    consecutive_thresholds: dict[str, int] = {}
    profile_b_cpu_samples = 0
    profile_b_rss_samples = 0
    stop_reason: str | None = None
    written_rows = 0
    for sample_index in range(args.samples):
        timestamp = time.time()
        host = _host_resources()
        rows.append({"sample": sample_index, "timestamp": timestamp, "kind": "host", "result": host})
        if host.get("available"):
            if int(host.get("memory_available_bytes") or 0) < 8 * 1024**3:
                stop_reason = stop_reason or "host_available_memory"
            if int(host.get("disk_free_bytes") or 0) < 20 * 1024**3:
                stop_reason = stop_reason or "host_free_disk"
        containers = _command("docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}")
        if not containers["available"]:
            rows.append({"sample": sample_index, "timestamp": timestamp, "kind": "containers", "available": False, "error_class": containers["stderr_class"]})
            stop_reason = stop_reason or "owned_container_enumeration_unavailable"
        else:
            container_ids = containers["stdout"].splitlines()
            stats_by_container = _stats_for_containers(container_ids)
            for container in container_ids:
                inspect = _command(
                    "docker",
                    "inspect",
                    container,
                    "--format",
                    "{{json .Config.Labels}} status={{.State.Status}} oom={{.State.OOMKilled}} restart={{.RestartCount}} memory={{.HostConfig.Memory}}",
                )
                if not inspect["available"] or expected_run not in inspect["stdout"]:
                    rows.append({"sample": sample_index, "timestamp": timestamp, "kind": "container", "available": False, "container": container, "error_class": "ownership_mismatch"})
                    stop_reason = stop_reason or "owned_container_ownership_mismatch"
                    continue
                parsed = stats_by_container[container]
                if not parsed.get("available", True):
                    stop_reason = stop_reason or "owned_container_stats_unavailable"
                rows.append({"sample": sample_index, "timestamp": timestamp, "kind": "container", "container": container, "available": bool(parsed.get("available", True)), "stats": parsed, "inspect": inspect["stdout"]})
                if resource_profile == "profile-b" and _service_container(project, "app") == container:
                    reason, profile_b_cpu_samples, profile_b_rss_samples, normalized = _profile_b_breach_reason(
                        parsed, inspect["stdout"], previous_cpu=profile_b_cpu_samples,
                        previous_rss=profile_b_rss_samples, cpu_quota=app_cpu_quota,
                        memory_quota_bytes=app_memory_quota_bytes,
                    )
                    rows[-1]["normalized"] = normalized
                elif resource_profile == "profile-b":
                    reason = "owned_container_restart_or_oom" if "oom=true" in inspect["stdout"].lower() or re.search(r"restart=[1-9]\d*", inspect["stdout"]) else None
                else:
                    reason, count = _breach_reason(
                        parsed,
                        inspect["stdout"],
                        previous=consecutive_thresholds.get(container, 0),
                        cpu_stop_percent=cpu_stop_percent,
                        cpu_emergency_percent=cpu_emergency_percent,
                    )
                    consecutive_thresholds[container] = count
                stop_reason = stop_reason or reason
        postgres = _service_container(project, "postgres")
        redis = _service_container(project, "redis")
        queue = _exec(postgres, "psql -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -Atc \"SELECT COALESCE(status,'') || ':' || count(*) FROM uploaded_files GROUP BY status ORDER BY status; SELECT COALESCE(EXTRACT(EPOCH FROM NOW()-MIN(created_at))::bigint,-1) FROM uploaded_files WHERE status NOT IN ('completed','failed','deleted')\"")
        rows.extend([
            {"sample": sample_index, "timestamp": timestamp, "kind": "postgres_connections", "result": _exec(postgres, "psql -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -Atc \"SELECT state || ':' || count(*) FROM pg_stat_activity GROUP BY state ORDER BY state\"")},
            {"sample": sample_index, "timestamp": timestamp, "kind": "postgres_activity", "result": _exec(postgres, "psql -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -Atc \"SELECT count(*) FROM pg_stat_activity WHERE state='active'\"")},
            {"sample": sample_index, "timestamp": timestamp, "kind": "postgres_lock_wait", "result": _exec(postgres, "psql -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -Atc \"SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock'\"")},
            {"sample": sample_index, "timestamp": timestamp, "kind": "upload_queue", "result": queue},
            {"sample": sample_index, "timestamp": timestamp, "kind": "redis", "result": _exec(redis, "redis-cli INFO memory stats")},
            {"sample": sample_index, "timestamp": timestamp, "kind": "metrics", "result": _metrics(metrics_url)},
            {"sample": sample_index, "timestamp": timestamp, "kind": "production_health", "result": _production_health()},
        ])
        if not rows[-1]["result"].get("healthy", False):
            stop_reason = stop_reason or "production_health_regression"
        if (_queue_age_seconds(queue) or -1) > 120:
            stop_reason = stop_reason or "upload_queue_age"
        stop_reason = stop_reason or _query_breach(run_dir)
        if stop_reason and stop_file is not None and not stop_file.exists():
            stop_file.write_text(json.dumps({"reason": stop_reason, "sample": sample_index}, ensure_ascii=True), encoding="utf-8")
            rows.append({"sample": sample_index, "timestamp": timestamp, "kind": "stop", "reason": stop_reason})
        if len(rows) > written_rows:
            with output.open("a", encoding="utf-8") as handle:
                for row in rows[written_rows:]:
                    handle.write(json.dumps(row, ensure_ascii=True) + "\n")
            written_rows = len(rows)
        if sample_index + 1 < args.samples:
            time.sleep(args.interval)
    rows.append({"kind": "collection_summary", "stop_reason": stop_reason or "", "samples": args.samples})
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
