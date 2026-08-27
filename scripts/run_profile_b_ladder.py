"""Execute exactly one manifest-owned Profile B rung on a Linux Docker host."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse


# The first five rungs are retained for backwards-compatible mock diagnostics;
# real-provider capacity acceptance is deliberately limited to the requested ladder.
STAGES = (1, 5, 10, 20, 30, 40, 50)
QWEN_STAGES = (10, 20, 30, 40, 50)
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
    if isinstance(error, subprocess.CalledProcessError) and step == "bootstrap" and error.returncode == 42:
        error_class = "application_rate_limit"
    elif isinstance(error, subprocess.CalledProcessError) and step == "bootstrap":
        error_class = "bootstrap_http_or_setup_failure"
    elif isinstance(error, subprocess.CalledProcessError):
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


def _validate_qwen_environment(environment: dict[str, str]) -> dict[str, str]:
    """Validate explicit, temporary Qwen inputs without ever echoing the key."""
    endpoint = str(environment.get("PERF_QWEN_ENDPOINT") or "").strip().rstrip("/")
    api_key = str(environment.get("PERF_QWEN_API_KEY") or "").strip()
    model = str(environment.get("PERF_QWEN_MODEL") or "").strip()
    embedding_model = str(environment.get("PERF_QWEN_EMBEDDING_MODEL") or "").strip()
    quota_path = str(environment.get("PERF_QWEN_QUOTA_RECORD") or "").strip()
    if not endpoint or not api_key or not model or not embedding_model or not quota_path:
        raise ValueError("qwen profile requires explicit temporary endpoint, key, chat model, embedding model, and quota record")
    parsed = urlparse(endpoint)
    allowed_hosts = {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"}
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        raise ValueError("qwen endpoint must be an approved DashScope HTTPS endpoint")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("qwen endpoint must not contain credentials or query parameters")
    if any(marker in endpoint.lower() for marker in ("prod", "production", "internal", "staging")):
        raise ValueError("qwen endpoint contains a forbidden environment marker")
    if len(api_key) < 12 or any(ch.isspace() for ch in api_key):
        raise ValueError("qwen API key is invalid")
    quota = Path(quota_path).resolve()
    temp_root = Path(os.environ.get("TMPDIR") or "/tmp").resolve()
    if not quota.is_file() or temp_root not in quota.parents:
        raise ValueError("qwen quota record must be an existing file below the temporary directory")
    try:
        payload = json.loads(quota.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("qwen quota record is unreadable") from error
    if not isinstance(payload, dict) or payload.get("provider") != "qwen":
        raise ValueError("qwen quota record must identify provider qwen")
    if str(payload.get("model") or "") != model:
        raise ValueError("qwen quota record model does not match the selected model")
    if str(payload.get("embedding_model") or "") != embedding_model:
        raise ValueError("qwen quota record embedding model does not match the selected embedding model")
    if not isinstance(payload.get("rpm"), (int, float)) or not isinstance(payload.get("tpm"), (int, float)):
        raise ValueError("qwen quota record must include numeric rpm and tpm")
    model_limits = payload.get("model_limits")
    if model_limits is not None:
        if not isinstance(model_limits, dict):
            raise ValueError("qwen quota model_limits must be an object")
        chat_limit = model_limits.get(model)
        embedding_limit = model_limits.get(embedding_model)
        for limit in (chat_limit, embedding_limit):
            if (
                not isinstance(limit, dict)
                or not isinstance(limit.get("rpm"), (int, float))
                or not isinstance(limit.get("tpm"), (int, float))
            ):
                raise ValueError("qwen quota model_limits must include numeric RPM and TPM for both selected models")
        if payload["rpm"] != min(chat_limit["rpm"], embedding_limit["rpm"]):
            raise ValueError("qwen quota record RPM must equal the selected-model bottleneck")
        if payload["tpm"] != min(chat_limit["tpm"], embedding_limit["tpm"]):
            raise ValueError("qwen quota record TPM must equal the selected-model bottleneck")
    # Return only non-sensitive values for the shell environment and report.
    return {"endpoint": endpoint, "model": model, "embedding_model": embedding_model, "quota_record": str(quota), "rpm": str(payload["rpm"]), "tpm": str(payload["tpm"])}


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
    allowed_phase_names = {
        "accepted_to_agent_info_ms",
        "agent_info_to_retrieval_ms",
        "retrieval_to_first_chunk_ms",
        "first_chunk_to_done_ms",
        "accepted_to_first_chunk_ms",
        "accepted_to_done_ms",
    }
    phase_summary = {
        name: dict(values or {})
        for name, values in dict(summary.get("sse_phase_ms") or {}).items()
        if name in allowed_phase_names and isinstance(values, dict)
    }
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
        "sse_phase_ms": phase_summary,
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


def _runtime_failure_signals(root: Path, run_dir: Path, manifest: dict) -> list[str]:
    """Extract fixed failure classes from owned app logs without retaining text."""
    compose = root / "tests" / "perf" / "compose.cloud.perf.yml"
    project = str(manifest.get("project") or "")
    if not project or not compose.is_file():
        return []
    try:
        output = subprocess.run(
            ["docker", "compose", "--project-name", project, "--env-file", str(run_dir / "compose.env"),
             "-f", str(compose), "logs", "--no-color", "--tail", "200", "app"],
            env=os.environ.copy(), capture_output=True, text=True, timeout=30,
        ).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return []
    signals: set[str] = set()
    if any(marker in output for marker in ("provider_call_leases", "provider_waiters", "provider unavailable", "provider profile unavailable", "pg pool", "undefinedtablename", "does not exist")):
        signals.add("provider_governance_or_database")
    if any(marker in output for marker in ("401", "unauthorized", "api key", "authentication", "forbidden")):
        signals.add("auth")
    if any(marker in output for marker in ("timeout", "timed out", "timedout", "超时")):
        signals.add("timeout")
    if any(marker in output for marker in ("embedding", "vector", "embed")):
        signals.add("embedding")
    return sorted(signals)


def _provider_db_smoke(root: Path, run_dir: Path, manifest: dict) -> str:
    """Run one content-free lease probe inside the owned app container."""
    compose = root / "tests" / "perf" / "compose.cloud.perf.yml"
    project = str(manifest.get("project") or "")
    if not project or not compose.is_file():
        return "unavailable"
    script = (
        "import asyncio, os, uuid\n"
        "from raganything.services.pg_state_repo import init_pg_pool, close_pg_pool\n"
        "from raganything.services.provider_governance_repo import provider_governance_repository\n"
        "async def main():\n"
        "  await init_pg_pool()\n"
        "  lease = await provider_governance_repository.acquire('smoke-fingerprint','smoke-owner','smoke-request',0,1,10)\n"
        "  if lease is None: raise RuntimeError('admission_denied')\n"
        "  await provider_governance_repository.release(lease.id, lease.owner_fence, 'smoke')\n"
        "  await close_pg_pool()\n"
        "asyncio.run(main())\n"
    )
    try:
        completed = subprocess.run(
            ["docker", "compose", "--project-name", project, "--env-file", str(run_dir / "compose.env"),
             "-f", str(compose), "exec", "-T", "app", "python", "-c", script],
            env=os.environ.copy(), capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    output = (completed.stdout + "\n" + completed.stderr).lower()
    if completed.returncode == 0:
        return "passed"
    if "provider_call_leases" in output and ("does not exist" in output or "undefinedtable" in output):
        return "schema_missing"
    if "timeout" in output or "timed out" in output:
        return "timeout"
    if "admission_denied" in output:
        return "admission_denied"
    return "db_error"


def _runtime_config_presence(root: Path, run_dir: Path, manifest: dict) -> dict[str, str]:
    compose = root / "tests" / "perf" / "compose.cloud.perf.yml"
    project = str(manifest.get("project") or "")
    if not project or not compose.is_file():
        return {}
    try:
        completed = subprocess.run(
            ["docker", "compose", "--project-name", project, "--env-file", str(run_dir / "compose.env"),
             "-f", str(compose), "exec", "-T", "app", "python", "-c",
             "import os,json; p=os.getenv(\"MODEL_PROFILE_CATALOG_FILE\",\"\"); profiles=[]; file_state=\"missing\";\ntry:\n data=json.load(open(p,encoding=\"utf-8\")); profiles=[str(x.get(\"id\")) for x in data.get(\"profiles\",[]) if isinstance(x,dict)]; file_state=\"present\"\nexcept Exception: pass\nprint(json.dumps({**{k:(\"present\" if os.getenv(k) else \"missing\") for k in (\"LLM_BINDING_HOST\",\"LLM_BINDING_API_KEY\",\"LLM_MODEL\",\"EMBEDDING_MODEL\",\"EMBEDDING_DIM\",\"DATABASE_URL\")},\"catalog_file\":file_state,\"catalog_legacy_llm\":(\"present\" if \"legacy-llm\" in profiles else \"missing\"),\"catalog_legacy_embedding\":(\"present\" if \"legacy-embedding\" in profiles else \"missing\")}))"],
            env=os.environ.copy(), capture_output=True, text=True, timeout=30,
        )
        if completed.returncode == 0:
            for line in reversed(completed.stdout.splitlines()):
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and set(value) >= {"LLM_BINDING_HOST", "EMBEDDING_MODEL"}:
                    return {str(k): str(v) for k, v in value.items()}
    except (OSError, subprocess.SubprocessError):
        pass
    return {}


def _provider_embedding_smoke(root: Path, run_dir: Path, manifest: dict) -> str:
    """Call the real governed embedding adapter inside the running app."""
    compose = root / "tests" / "perf" / "compose.cloud.perf.yml"
    project = str(manifest.get("project") or "")
    if not project or not compose.is_file():
        return "unavailable"
    script = (
        "import asyncio, os, uuid\n"
        "from raganything.services.pg_state_repo import init_pg_pool, close_pg_pool\n"
        "from raganything.services.vision_models import govern_openai_compatible_call\n"
        "from raganything.services.provider_governance import ProviderPriority\n"
        "from lightrag.llm.openai import openai_embed\n"
        "async def main():\n"
        "  await init_pg_pool()\n"
        "  result = await asyncio.wait_for(govern_openai_compatible_call(os.environ['EMBEDDING_MODEL'], os.environ['LLM_BINDING_HOST'], lambda: openai_embed.func(['health'], model=os.environ['EMBEDDING_MODEL'], api_key=os.environ['LLM_BINDING_API_KEY'], base_url=os.environ['LLM_BINDING_HOST'], client_configs={'timeout':20,'max_retries':0}), capability='embedding', priority=ProviderPriority.UPLOAD), 30)\n"
        "  print('passed' if result is not None and len(result) == 1 and len(result[0]) == int(os.environ.get('EMBEDDING_DIM','1024')) else 'invalid_response')\n"
        "  await close_pg_pool()\n"
        "asyncio.run(main())\n"
    )
    try:
        completed = subprocess.run(
            ["docker", "compose", "--project-name", project, "--env-file", str(run_dir / "compose.env"),
             "-f", str(compose), "exec", "-T", "app", "python", "-c", script],
            env=os.environ.copy(), capture_output=True, text=True, timeout=45,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    if completed.returncode == 0 and "passed" in completed.stdout.splitlines():
        return "passed"
    output = (completed.stdout + "\n" + completed.stderr).lower()
    if "timeout" in output or "timed out" in output:
        return "timeout"
    return "request_error"


def _provider_llm_smoke(root: Path, run_dir: Path, manifest: dict) -> str:
    """Call the real governed chat adapter inside the running app."""
    compose = root / "tests" / "perf" / "compose.cloud.perf.yml"
    project = str(manifest.get("project") or "")
    if not project or not compose.is_file():
        return "unavailable"
    script = (
        "import asyncio, os\n"
        "from raganything.services.pg_state_repo import init_pg_pool, close_pg_pool\n"
        "from raganything.services.vision_models import govern_openai_compatible_call\n"
        "from raganything.services.provider_governance import ProviderPriority\n"
        "from lightrag.llm.openai import openai_complete_if_cache\n"
        "async def main():\n"
        "  await init_pg_pool()\n"
        "  result = await asyncio.wait_for(govern_openai_compatible_call(os.environ['LLM_MODEL'], os.environ['LLM_BINDING_HOST'], lambda: openai_complete_if_cache(os.environ['LLM_MODEL'], 'Reply with OK.', api_key=os.environ['LLM_BINDING_API_KEY'], base_url=os.environ['LLM_BINDING_HOST'], max_tokens=1, timeout=20), capability='llm', priority=ProviderPriority.UPLOAD), 30)\n"
        "  print('passed' if isinstance(result,str) and result.strip() else 'invalid_response')\n"
        "  await close_pg_pool()\n"
        "asyncio.run(main())\n"
    )
    try:
        completed = subprocess.run(
            ["docker", "compose", "--project-name", project, "--env-file", str(run_dir / "compose.env"),
             "-f", str(compose), "exec", "-T", "app", "python", "-c", script],
            env=os.environ.copy(), capture_output=True, text=True, timeout=45,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    if completed.returncode == 0 and "passed" in completed.stdout.splitlines():
        return "passed"
    output = (completed.stdout + "\n" + completed.stderr).lower()
    if "timeout" in output or "timed out" in output:
        return "timeout"
    if any(marker in output for marker in ("401", "unauthorized", "api key", "authentication", "forbidden")):
        return "auth_error"
    return "request_error"


def _create_rag_smoke(root: Path, run_dir: Path, manifest: dict) -> str:
    """Exercise text-upload RAG initialization and embedding preflight safely."""
    compose = root / "tests" / "perf" / "compose.cloud.perf.yml"
    project = str(manifest.get("project") or "")
    if not project or not compose.is_file():
        return "unavailable"
    script = (
        "import asyncio, os\n"
        "from raganything.embedding.identity import text_embedding_identity_from_environment\n"
        "from raganything.services.pg_state_repo import init_pg_pool, close_pg_pool\n"
        "from raganything.services.kb_service import create_rag\n"
        "from raganything.services.vision_models import load_catalog\n"
        "async def main():\n"
        "  stage = 'pg_storage_error'\n"
        "  outcome = 'request_error'\n"
        "  try:\n"
        "    await init_pg_pool()\n"
        "    stage = 'snapshot_profile_error'\n"
        "    catalog = load_catalog(refresh=True)\n"
        "    llm = catalog.get('legacy-llm')\n"
        "    vlm = catalog.get('legacy-vlm')\n"
        "    if llm is None or vlm is None: raise RuntimeError('profile_missing')\n"
        "    task_settings = {'fingerprint':'worker-smoke','models':{'llm_profile_id':'legacy-llm','vlm_profile_id':'legacy-vlm'},'profile_fingerprints':{'llm':llm.fingerprint,'vlm':vlm.fingerprint},'text_embedding_identity':text_embedding_identity_from_environment(),'ingestion':{'parser':'docling','chunking_strategy':'recursive','chunk_size':800,'enable_image':False,'enable_table':False,'enable_equation':False,'enable_video':False,'entity_types':[],'minimum_relation_degree':0,'parsers_by_type':{},'video_index_profile_version':'v2'},'runtime':{'llm_timeout':180,'personal_concurrency':7},'_query_scope':{'workspace':'/app/rag_storage/worker-smoke','permission_scope':'background','corpus_revision':'smoke','settings_fingerprint':'worker-smoke','llm_profile_fingerprint':llm.fingerprint}}\n"
        "    stage = 'rag_construct_error'\n"
        "    rag = await create_rag(working_dir='/app/rag_storage/worker-smoke', chunking_strategy='recursive', task_settings=task_settings)\n"
        "    rag.disable_atexit_cleanup()\n"
        "    stage = 'lightrag_init_error'\n"
        "    initialized = await rag._ensure_lightrag_initialized()\n"
        "    if not isinstance(initialized, dict) or not initialized.get('success'):\n"
        "      detail = str(initialized.get('error') or '').lower() if isinstance(initialized, dict) else ''\n"
        "      if 'parser' in detail and 'not properly installed' in detail: stage = 'parser_unavailable'\n"
        "      elif any(marker in detail for marker in ('postgres', 'pgkvstorage', 'pgdocstatusstorage', 'pgvectorstorage', 'database')): stage = 'pg_storage_error'\n"
        "      raise RuntimeError('initialization_failed')\n"
        "    stage = 'provider_missing'\n"
        "    provider = getattr(rag, '_raw_embedding_preflight_provider', None)\n"
        "    if provider is None: raise RuntimeError('provider_missing')\n"
        "    stage = 'provider_error'\n"
        "    result = await asyncio.wait_for(provider(['health'], timeout=20), 30)\n"
        "    if result is None or len(result) != 1 or len(result[0]) != int(os.environ.get('EMBEDDING_DIM','1024')): raise RuntimeError('invalid_response')\n"
        "    stage = 'text_insert_error'\n"
        "    try:\n"
        "      await asyncio.wait_for(rag.insert_content_list([{'type':'text','text':'Synthetic isolated worker diagnostic text.','page_idx':0}], file_path='worker-smoke.txt', chunking_strategy='recursive', track_id=str(uuid.uuid4())), 45)\n"
        "    except asyncio.TimeoutError: raise\n"
        "    except Exception as error:\n"
        "      detail = (type(error).__name__ + ' ' + str(error)).lower()\n"
        "      if any(marker in detail for marker in ('provider', 'dashscope', '429', '503', 'provider_busy')): stage = 'provider_error'\n"
        "      elif any(marker in detail for marker in ('embedding', 'vector', 'embed')): stage = 'embedding_pipeline_error'\n"
        "      elif any(marker in detail for marker in ('postgres', 'database', 'pgvector', 'connection')): stage = 'pg_storage_error'\n"
        "      elif any(marker in detail for marker in ('llm', 'completion', 'entity')): stage = 'llm_pipeline_error'\n"
        "      elif isinstance(error, TypeError): stage = 'ainsert_contract_error'\n"
        "      elif isinstance(error, KeyError): stage = 'storage_schema_error'\n"
        "      elif isinstance(error, (AssertionError, AttributeError)): stage = 'ainsert_runtime_error'\n"
        "      raise\n"
        "    outcome = 'passed'\n"
        "  except asyncio.TimeoutError:\n"
        "    outcome = 'timeout'\n"
        "  except Exception:\n"
        "    outcome = stage\n"
        "  finally:\n"
        "    if 'rag' in locals():\n"
        "      try: await asyncio.wait_for(rag.finalize_storages(worker_vdb_persistence=True), 20)\n"
        "      except asyncio.TimeoutError:\n"
        "        if outcome == 'passed': outcome = 'finalize_timeout'\n"
        "      except Exception:\n"
        "        if outcome == 'passed': outcome = 'finalize_error'\n"
        "    try: await close_pg_pool()\n"
        "    except Exception:\n"
        "      if outcome == 'passed': outcome = 'close_error'\n"
        "    print('passed' if outcome == 'passed' else 'smoke_failure=' + outcome)\n"
        "asyncio.run(main())\n"
    )
    try:
        completed = subprocess.run(
            ["docker", "compose", "--project-name", project, "--env-file", str(run_dir / "compose.env"),
             "-f", str(compose), "exec", "-T", "app", "python", "-c", script],
            # The inner insert is deliberately bounded at 45 seconds, but
            # first-use storage initialization and process startup also need
            # time. Keep the outer command longer so it reports that inner
            # timeout instead of an ambiguous executor failure.
            env=os.environ.copy(), capture_output=True, text=True, timeout=150,
        )
    except subprocess.TimeoutExpired:
        return "timeout"
    except OSError:
        return "unavailable"
    if completed.returncode == 0 and "passed" in completed.stdout.splitlines():
        return "passed"
    output = (completed.stdout + "\n" + completed.stderr).lower()
    for outcome in (
        "snapshot_profile_error", "rag_construct_error", "parser_unavailable",
        "lightrag_init_error", "pg_storage_error", "provider_missing",
        "provider_error", "embedding_pipeline_error", "llm_pipeline_error",
        "ainsert_contract_error", "storage_schema_error", "ainsert_runtime_error",
        "text_insert_error", "finalize_timeout", "finalize_error", "close_error",
        "timeout",
    ):
        if f"smoke_failure={outcome}" in output:
            return outcome
    if "timeout" in output or "timed out" in output:
        return "timeout"
    if "provider_missing" in output:
        return "provider_missing"
    return "request_error"


def _resource_summary(rows: list[dict]) -> dict:
    normalized = [row.get("normalized") for row in rows if isinstance(row.get("normalized"), dict)]
    production = [row for row in rows if row.get("kind") == "production_health"]
    metric_results = [
        row.get("result") for row in rows
        if row.get("kind") == "metrics" and isinstance(row.get("result"), dict)
    ]
    return {
        "sample_count": sum(row.get("kind") == "host" for row in rows),
        "stop_count": sum(row.get("kind") == "stop" for row in rows),
        "production_probe_samples": len(production),
        "production_probes_healthy": bool(production) and all(row.get("result", {}).get("healthy", False) for row in production),
        "app_cpu_percent_of_quota_peak": max((float(row.get("cpu_percent_of_quota") or 0) for row in normalized), default=0.0),
        "app_rss_percent_of_quota_peak": max((float(row.get("rss_percent_of_quota") or 0) for row in normalized), default=0.0),
        "metrics_available_samples": sum(bool(row.get("available")) for row in metric_results),
        "query_phase_histogram_samples": sum(bool(row.get("query_phase_histogram")) for row in metric_results),
        "provider_governance_metric_samples": sum(bool(row.get("provider_governance_metrics")) for row in metric_results),
    }


def _retrieval_gate_summary(path: Path) -> dict:
    """Keep a failed readiness gate diagnosable after isolated cleanup."""
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False}
    if not isinstance(rows, list):
        return {"available": False}
    entries = [row for row in rows if isinstance(row, dict)]
    uploads = [row.get("upload") for row in entries if isinstance(row.get("upload"), dict)]
    queries = [row.get("retrieval_query") for row in entries if isinstance(row.get("retrieval_query"), dict)]
    upload_outcomes = {
        "retrieval_ready": 0,
        "completed_without_retrieval": 0,
        "terminal_not_completed": 0,
        "upload_http_4xx": 0,
        "upload_http_5xx": 0,
        "other": 0,
    }
    terminal_failure_stages = {name: 0 for name in (
        "initializing", "model_preflight", "parsing", "embedding", "vlm_ocr",
        "ocr", "indexing", "entity_extraction", "graph_index", "finalize",
        "quota", "retrieval_readiness", "tagging", "timeout", "video_processing",
        "worker", "other",
    )}
    terminal_failure_families = {name: 0 for name in ("embedding", "provider", "timeout", "auth", "database", "retrieval", "other")}
    for upload in uploads:
        classification = str(upload.get("classification") or "")
        if classification == "retrieval_ready":
            bucket = "retrieval_ready"
        elif classification == "completed_not_retrieval_ready":
            bucket = "completed_without_retrieval"
        elif classification.startswith("terminal_"):
            bucket = "terminal_not_completed"
        elif classification.startswith("upload_http_4"):
            bucket = "upload_http_4xx"
        elif classification.startswith("upload_http_5"):
            bucket = "upload_http_5xx"
        else:
            bucket = "other"
        upload_outcomes[bucket] += 1
        if bucket == "terminal_not_completed":
            stage = str(upload.get("terminal_failure_stage") or "other")
            family = str(upload.get("terminal_failure_family") or "other")
            terminal_failure_stages[stage if stage in terminal_failure_stages else "other"] += 1
            terminal_failure_families[family if family in terminal_failure_families else "other"] += 1
    return {
        "available": True,
        "virtual_users": len(entries),
        "uploads_retrieval_ready": sum(row.get("classification") == "retrieval_ready" for row in uploads),
        "upload_outcomes": upload_outcomes,
        "terminal_failure_stages": terminal_failure_stages,
        "terminal_failure_families": terminal_failure_families,
        "retrieval_queries_attempted": sum(row.get("outcome") != "skipped" for row in queries),
        "retrieval_queries_success": sum(row.get("outcome") == "success" for row in queries),
        "retrieval_queries_with_source": sum(
            row.get("outcome") == "success" and int(row.get("retrieval_source_count") or 0) > 0
            for row in queries
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, choices=STAGES, required=True)
    parser.add_argument("--app-image", required=True)
    parser.add_argument("--predecessor")
    parser.add_argument("--report-root", required=True)
    parser.add_argument("--direct-50-diagnostic", action="store_true")
    parser.add_argument("--diagnose-text-insert", action="store_true")
    parser.add_argument("--provider-profile", choices=("mock", "qwen"), default="mock")
    args = parser.parse_args()
    if args.provider_profile == "qwen" and args.stage not in QWEN_STAGES:
        raise ValueError("qwen provider profile requires one of stages 10, 20, 30, 40, or 50")
    if args.provider_profile == "qwen" and args.direct_50_diagnostic:
        raise ValueError("qwen provider profile requires the ordered 10, 20, 30, 40, 50 ladder")
    if args.diagnose_text_insert and (
        args.provider_profile != "qwen" or args.stage != 10
        or args.predecessor or args.direct_50_diagnostic
    ):
        raise ValueError("text insert diagnostic requires qwen stage 10 without predecessor or direct mode")
    qwen = _validate_qwen_environment(dict(os.environ)) if args.provider_profile == "qwen" else None
    if args.direct_50_diagnostic and (args.stage != 50 or args.predecessor):
        raise ValueError("direct Profile B diagnostic requires stage 50 without predecessor evidence")
    first_stage = 10 if args.provider_profile == "qwen" else 1
    if not args.direct_50_diagnostic and args.stage != first_stage and not args.predecessor:
        raise ValueError("later Profile B stages require a predecessor report")
    if args.predecessor and not Path(args.predecessor).is_file():
        raise ValueError("later Profile B stages require an existing sanitized predecessor report")

    root = Path(__file__).resolve().parents[1]
    runner = root / "scripts" / "run_isolated_cloud_perf.sh"
    workload = root / "scripts" / "run_cloud_perf_workload.py"
    collector = root / "scripts" / "collect_perf_resources.py"
    environment = dict(os.environ)
    report_root = Path(args.report_root).resolve()
    report_root.mkdir(parents=True, exist_ok=True)
    progress_path = report_root / "runner-progress.ndjson"
    environment.update({
        "PERF_APP_IMAGE": args.app_image,
        "PERF_REPORT_ROOT": str(report_root),
        "PERF_RESOURCE_PROFILE": "profile-b",
        "PERF_PROFILE_B_AUTHORIZATION": "profile-b-8cpu-24g-direct-50" if args.direct_50_diagnostic else "profile-b-4cpu-6g-ladder",
        "PERF_PROFILE_B_STAGE": str(args.stage),
        "PERF_DIAGNOSTIC_MODE": "profile-b",
        "PERF_RATE_LIMIT_MODE": "capacity",
        "PERF_ENABLE_CPU_PROFILE": "0",
        "PERF_SSE_PHASE_ATTRIBUTION": "0",
        "PERF_PROFILE_B_EXECUTION_MODE": "direct-50-diagnostic" if args.direct_50_diagnostic else "ordered-ladder",
        "PERF_RUNNER_PROGRESS_FILE": str(progress_path),
        "PERF_PROVIDER_PROFILE": args.provider_profile,
    })
    if qwen:
        environment.update({
            "PERF_QWEN_ENDPOINT": qwen["endpoint"],
            "PERF_QWEN_MODEL": qwen["model"],
            "PERF_QWEN_EMBEDDING_MODEL": qwen["embedding_model"],
            "PERF_QWEN_QUOTA_RECORD": qwen["quota_record"],
            "PERF_QWEN_RPM": qwen["rpm"],
            "PERF_QWEN_TPM": qwen["tpm"],
            "PERF_QWEN_QUOTA_VERIFIED": "true",
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
    exit_status = 0
    try:
        if args.diagnose_text_insert:
            _write_progress(progress_path, "text_insert_diagnostic_start")
            outcome = _create_rag_smoke(root, run_dir, manifest)
            result = {
                "classification": "profile_b_text_insert_diagnostic",
                "requests": 0,
                "successes": 0,
                "ttft_p95_ms": None,
                "total_p95_ms": None,
                "recovery_passed": False,
                "text_insert_diagnostic": outcome,
            }
            result_path.write_text(json.dumps(result, ensure_ascii=True, sort_keys=True), encoding="utf-8")
            _write_progress(progress_path, "text_insert_diagnostic_complete")
            print(f"text-insert-diagnostic={outcome}", flush=True)
            return 0 if outcome == "passed" else 1
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
            exit_status = 1
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
        gate = _retrieval_gate_summary(run_dir / "retrieval-gate.json")
        if result.get("failure_step") == "readiness" and gate["available"]:
            result["classification"] = "profile_b_readiness_gate_failed"
            result["failure_class"] = "retrieval_gate_failed"
            result["retrieval_gate"] = gate
            result["runtime_failure_signals"] = _runtime_failure_signals(root, run_dir, manifest)
            result["provider_db_smoke"] = _provider_db_smoke(root, run_dir, manifest)
            result["runtime_config_presence"] = _runtime_config_presence(root, run_dir, manifest)
            result["provider_embedding_smoke"] = _provider_embedding_smoke(root, run_dir, manifest)
            result["provider_llm_smoke"] = _provider_llm_smoke(root, run_dir, manifest)
            result["create_rag_smoke"] = _create_rag_smoke(root, run_dir, manifest)
        exit_status = 1
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
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
