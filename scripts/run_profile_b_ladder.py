"""Execute exactly one manifest-owned Profile B rung on a Linux Docker host."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


STAGES = (1, 5, 10, 20, 30, 40, 50)
RECOVERY_SECONDS = 600
SAMPLE_SECONDS = 5
RECOVERY_SAMPLES = RECOVERY_SECONDS // SAMPLE_SECONDS


class RunnerStageError(RuntimeError):
    """A content-free failure classification for an owned ladder step."""

    def __init__(self, step: str, error: BaseException) -> None:
        super().__init__(step)
        self.step = step
        self.error = error


def _failure_classification(error: BaseException) -> dict:
    if isinstance(error, RunnerStageError):
        step = error.step
        error = error.error
    else:
        step = "runner"
    if isinstance(error, subprocess.CalledProcessError):
        error_class = "subprocess_failed"
    elif isinstance(error, subprocess.TimeoutExpired):
        error_class = "subprocess_timeout"
    elif isinstance(error, (json.JSONDecodeError, KeyError, ValueError)):
        error_class = "invalid_owned_result"
    elif isinstance(error, OSError):
        error_class = "local_io_failure"
    else:
        error_class = "unexpected_runner_exception"
    return {"failure_step": step, "failure_class": error_class}


def _step(name: str, action):
    try:
        return action()
    except Exception as error:
        raise RunnerStageError(name, error) from error


def _run(command: list[str], environment: dict[str, str], *, timeout: int | None = None) -> None:
    subprocess.run(command, check=True, env=environment, timeout=timeout)


def _write_progress(path: Path, phase: str) -> None:
    """Persist a content-free phase marker for external, read-only monitoring."""
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": "runner_progress", "phase": phase, "timestamp": time.time()}) + "\n")


def _run_dir(output: str) -> Path:
    for line in output.splitlines():
        if line.startswith("run-directory="):
            return Path(line.partition("=")[2]).resolve()
    raise RuntimeError("runner did not report an isolated run directory")


def _recovery_outcome(recovery_rows: list[dict], collector_returncode: int) -> tuple[bool, str, str]:
    """Classify fixed, aggregate recovery evidence without retaining process output."""
    if collector_returncode:
        return False, "recovery_collector_process_failed", ""
    stop_reason = next((str(row.get("reason") or "") for row in recovery_rows if row.get("kind") == "stop"), "")
    if stop_reason:
        return False, "recovery_resource_stop", stop_reason
    host_samples = sum(row.get("kind") == "host" for row in recovery_rows)
    production_rows = [row for row in recovery_rows if row.get("kind") == "production_health"]
    summaries = [row for row in recovery_rows if row.get("kind") == "collection_summary"]
    if host_samples != RECOVERY_SAMPLES or len(production_rows) != RECOVERY_SAMPLES or len(summaries) != 1:
        return False, "recovery_evidence_incomplete", ""
    if summaries[0].get("samples") != RECOVERY_SAMPLES or summaries[0].get("stop_reason"):
        return False, "recovery_evidence_incomplete", ""
    if not all(row.get("result", {}).get("healthy", False) for row in production_rows):
        return False, "recovery_production_health_unhealthy", ""
    return True, "", ""


def _profile_b_result(query: dict, recovery_rows: list[dict], *, recovery_returncode: int = 0) -> dict:
    summary = dict(query.get("profile_b") or {})
    timing = {name: dict(values or {}) for name, values in dict(summary.get("timing_ms") or {}).items()}
    recovery_healthy, recovery_failure_class, resource_stop_reason = _recovery_outcome(
        recovery_rows, recovery_returncode
    )
    passed = bool(summary.get("passed")) and recovery_healthy
    return {
        "classification": "profile_b_stage_passed" if passed else "profile_b_hard_stop",
        "requests": int(summary.get("requests") or 0),
        "successes": int(summary.get("successes") or 0),
        "ttft_p95_ms": summary.get("ttft_p95_ms"),
        "total_p95_ms": summary.get("total_p95_ms"),
        "timing_ms": timing,
        "latency_gates_ms": dict(summary.get("latency_gates_ms") or {}),
        "retries": int(summary.get("retries") or 0),
        "protocol_failures": int(summary.get("protocol_failures") or 0),
        "protocol_failure_classes": dict(summary.get("protocol_failure_classes") or {}),
        "stopped": bool(summary.get("stopped")),
        "recovery_passed": recovery_healthy,
        "recovery_failure_class": recovery_failure_class,
        "resource_stop_reason": resource_stop_reason,
    }


def _direct_50_classification(result: dict) -> str:
    return (
        "profile_b_direct_diagnostic_completed"
        if result.get("classification") == "profile_b_stage_passed"
        else "profile_b_direct_diagnostic_hard_stop"
    )


def _read_ndjson(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _resource_summary(rows: list[dict]) -> dict:
    normalized = [row.get("normalized") for row in rows if isinstance(row.get("normalized"), dict)]
    production = [row for row in rows if row.get("kind") == "production_health"]
    return {
        "sample_count": sum(row.get("kind") == "host" for row in rows),
        "stop_count": sum(row.get("kind") == "stop" for row in rows),
        "production_probe_samples": len(production),
        "production_probes_healthy": bool(production) and all(row.get("result", {}).get("healthy", False) for row in production),
        "app_cpu_percent_of_quota_peak": max((float(row.get("cpu_percent_of_quota") or 0) for row in normalized), default=0.0),
        "app_rss_percent_of_quota_peak": max((float(row.get("rss_percent_of_quota") or 0) for row in normalized), default=0.0),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, choices=STAGES, required=True)
    parser.add_argument("--app-image", required=True)
    parser.add_argument("--predecessor")
    parser.add_argument("--report-root", required=True)
    parser.add_argument("--direct-50-diagnostic", action="store_true")
    args = parser.parse_args()
    if args.direct_50_diagnostic and (args.stage != 50 or args.predecessor):
        raise ValueError("direct Profile B diagnostic requires stage 50 without predecessor evidence")
    if not args.direct_50_diagnostic and args.stage != 1 and not args.predecessor:
        raise ValueError("later Profile B stages require a predecessor report")

    root = Path(__file__).resolve().parents[1]
    runner = root / "scripts" / "run_isolated_cloud_perf.sh"
    workload = root / "scripts" / "run_cloud_perf_workload.py"
    collector = root / "scripts" / "collect_perf_resources.py"
    environment = dict(os.environ)
    progress_path = Path(args.report_root).resolve() / "runner-progress.ndjson"
    environment.update({
        "PERF_APP_IMAGE": args.app_image,
        "PERF_REPORT_ROOT": str(Path(args.report_root).resolve()),
        "PERF_RESOURCE_PROFILE": "profile-b",
        "PERF_PROFILE_B_AUTHORIZATION": "profile-b-8cpu-24g-direct-50" if args.direct_50_diagnostic else "profile-b-4cpu-6g-ladder",
        "PERF_PROFILE_B_STAGE": str(args.stage),
        "PERF_DIAGNOSTIC_MODE": "profile-b",
        "PERF_RATE_LIMIT_MODE": "capacity",
        "PERF_ENABLE_CPU_PROFILE": "0",
        "PERF_SSE_PHASE_ATTRIBUTION": "0",
        "PERF_PROFILE_B_EXECUTION_MODE": "direct-50-diagnostic" if args.direct_50_diagnostic else "ordered-ladder",
        "PERF_RUNNER_PROGRESS_FILE": str(progress_path),
    })
    if args.direct_50_diagnostic:
        environment["PERF_PROFILE_B_DIRECT_AUTHORIZATION"] = "profile-b-direct-50-8cpu-24g"
    if args.predecessor:
        environment["PERF_PROFILE_B_PREDECESSOR"] = str(Path(args.predecessor).resolve())
    _write_progress(progress_path, "preflight_start")
    print("profile-b-runner-step=preflight", flush=True)
    _run(["bash", str(runner), "preflight"], environment, timeout=60)
    _write_progress(progress_path, "preflight_complete")
    _write_progress(progress_path, "up_start")
    print("profile-b-runner-step=up", flush=True)
    up = subprocess.run(
        ["bash", str(runner), "up"], check=True, env=environment, text=True,
        capture_output=True, timeout=240,
    )
    run_dir = _run_dir(up.stdout)
    _write_progress(progress_path, "up_complete")
    environment["PERF_RUN_DIR"] = str(run_dir)
    manifest = json.loads(run_dir.joinpath("manifest.json").read_text(encoding="utf-8"))
    base_url = f"http://127.0.0.1:{manifest['loopback_port']}"
    result_path = run_dir / "profile-b-result.json"
    try:
        _write_progress(progress_path, "bootstrap_start")
        _step("bootstrap", lambda: _run([sys.executable, str(root / "scripts" / "bootstrap_perf_run.py"), "--base-url", base_url, "--run-dir", str(run_dir), "--env-file", str(run_dir / "compose.env"), "--users", str(args.stage), "--timeout", "300"], environment))
        _write_progress(progress_path, "bootstrap_complete")
        _write_progress(progress_path, "readiness_start")
        _step("readiness", lambda: _run([sys.executable, str(workload), "--mode", "readiness", "--base-url", base_url, "--run-dir", str(run_dir), "--users", str(args.stage), "--timeout", "300"], environment))
        _write_progress(progress_path, "readiness_complete")
        _write_progress(progress_path, "load_collection_start")
        collect = _step("load_collection_start", lambda: subprocess.Popen([sys.executable, str(collector), "--manifest", str(run_dir / "manifest.json"), "--output", str(run_dir / "load-resources.ndjson"), "--samples", "18", "--interval", "5", "--stop-file", str(run_dir / "stop-load.json")], env=environment))
        _write_progress(progress_path, "query_start")
        query_return = _step("query", lambda: subprocess.run([sys.executable, str(workload), "--mode", "query", "--base-url", base_url, "--run-dir", str(run_dir), "--users", str(args.stage), "--duration", "75", "--ramp", "15", "--timeout", "30", "--label", f"profile-b-{args.stage}"], env=environment).returncode)
        _write_progress(progress_path, "query_complete")
        _step("load_collection", lambda: collect.wait(timeout=120))
        _write_progress(progress_path, "load_collection_complete")
        _write_progress(progress_path, "recovery_start")
        recovery = _step("recovery_collection", lambda: subprocess.run([sys.executable, str(collector), "--manifest", str(run_dir / "manifest.json"), "--output", str(run_dir / "recovery-resources.ndjson"), "--samples", str(RECOVERY_SECONDS // SAMPLE_SECONDS), "--interval", str(SAMPLE_SECONDS)], env=environment).returncode)
        _write_progress(progress_path, "recovery_complete")
        query = _step("query_result", lambda: json.loads(run_dir.joinpath(f"query-profile-b-{args.stage}.json").read_text(encoding="utf-8")))
        load_rows = _step("load_result", lambda: _read_ndjson(run_dir / "load-resources.ndjson"))
        recovery_rows = _step("recovery_result", lambda: _read_ndjson(run_dir / "recovery-resources.ndjson"))
        result = _profile_b_result(query, recovery_rows, recovery_returncode=recovery)
        result["load_resources"] = _resource_summary(load_rows)
        result["recovery_resources"] = _resource_summary(recovery_rows)
        if query_return or recovery:
            result["classification"] = "profile_b_hard_stop"
        if recovery:
            result["recovery_passed"] = False
        if args.direct_50_diagnostic:
            result["classification"] = _direct_50_classification(result)
            result["ordered_ladder_eligible"] = False
        result_path.write_text(json.dumps(result, ensure_ascii=True, sort_keys=True), encoding="utf-8")
        _write_progress(progress_path, "result_recorded")
    except Exception as error:
        result = {
            "classification": "profile_b_invalid_or_preflight_failed",
            "requests": 0,
            "successes": 0,
            "ttft_p95_ms": None,
            "total_p95_ms": None,
            "recovery_passed": False,
            "resource_stop_reason": "runner_failure",
        }
        result.update(_failure_classification(error))
        if args.direct_50_diagnostic:
            result["classification"] = "profile_b_direct_diagnostic_hard_stop"
            result["ordered_ladder_eligible"] = False
        result_path.write_text(json.dumps(result, ensure_ascii=True, sort_keys=True), encoding="utf-8")
        _write_progress(progress_path, "result_recorded")
    finally:
        _write_progress(progress_path, "cleanup_start")
        _run(["bash", str(runner), "record-profile-b-result"], environment)
        _run(["bash", str(runner), "down"], environment)
        _write_progress(progress_path, "cleanup_complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
