#!/usr/bin/env bash
# Run an owned, mock-backed capacity stack on a Linux Docker host.
set -euo pipefail

phase=${1:-}
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
compose_file="$repo_root/tests/perf/compose.cloud.perf.yml"
temp_root=$(realpath "${TMPDIR:-/tmp}")
run_dir=${PERF_RUN_DIR:-}
app_image=${PERF_APP_IMAGE:-}
marker_image=${PERF_MARKER_IMAGE:-raganything-marker:parsers}
nginx_image=${PERF_NGINX_IMAGE:-raganything-nginx:fast-afe40d360576}
postgres_image=${PERF_POSTGRES_IMAGE:-pgvector/pgvector:pg16}
redis_image=${PERF_REDIS_IMAGE:-redis:7-alpine}
report_root=${PERF_REPORT_ROOT:-"$repo_root/outputs/isolated-cloud-perf"}
rate_limit_mode=${PERF_RATE_LIMIT_MODE:-enforced}
cpu_profiling=${PERF_ENABLE_CPU_PROFILE:-0}
sse_phase_attribution=${PERF_SSE_PHASE_ATTRIBUTION:-0}
diagnostic_mode=${PERF_DIAGNOSTIC_MODE:-standard}
diagnostic_stage=${PERF_DIAGNOSTIC_STAGE:-}
resource_profile=${PERF_RESOURCE_PROFILE:-profile-a}
profile_b_stage=${PERF_PROFILE_B_STAGE:-}
profile_b_predecessor=${PERF_PROFILE_B_PREDECESSOR:-}
profile_b_execution_mode=${PERF_PROFILE_B_EXECUTION_MODE:-ordered-ladder}
profile_b_max_async=4
progress_file=${PERF_RUNNER_PROGRESS_FILE:-}
profile_b_8c32g_direct=false
if [[ "$resource_profile" == profile-b && "$profile_b_execution_mode" == direct-50-diagnostic ]]; then
    profile_b_8c32g_direct=true
fi

die() { printf '%s\n' "cloud-perf: $*" >&2; exit 2; }
progress() { [[ -z "$progress_file" ]] || printf '{"kind":"runner_progress","step":"%s"}\n' "$1" >>"$progress_file"; }
require() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }
secret() { od -An -N32 -tx1 /dev/urandom | tr -d ' \n'; }

resolve_image_id() {
    local reference=$1 image_id
    image_id=$(docker image inspect "$reference" --format '{{.Id}}') || die "image is unavailable: $reference"
    [[ "$image_id" == sha256:* ]] || die "image did not resolve to an immutable local ID: $reference"
    printf '%s\n' "$image_id"
}

assert_child_of_tmp() {
    local resolved
    resolved=$(realpath -m "$1")
    [[ "$resolved" != "$temp_root" && "$resolved" == "$temp_root"/* ]] || die "run directory must be below $temp_root"
    python3 "$repo_root/scripts/cloud_perf_manifest.py" assert-temp-child "$temp_root" "$resolved"
}

free_memory_gib() {
    awk '/MemAvailable:/ { printf "%.2f", $2 / 1048576 }' /proc/meminfo
}

free_disk_gib() {
    df -Pk "$temp_root" | awk 'NR == 2 { printf "%.2f", $4 / 1048576 }'
}

unused_loopback_port() {
    python3 - <<'PY'
import socket
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

new_run_dir() {
    python3 - "$temp_root" <<'PY'
import secrets
import sys
print(f"{sys.argv[1]}/raganything-cloud-perf-{secrets.token_hex(12)}")
PY
}

manifest_value() {
    python3 - "$run_dir/manifest.json" "$1" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]])
PY
}

write_production_probe() {
    local output=$1 phase_name=$2
    python3 - "$output" "$phase_name" <<'PY'
import json
import sys

json.dump({"phase": sys.argv[2], "containers": {}, "endpoints": {}}, open(sys.argv[1], "w", encoding="utf-8"))
PY
    local container value endpoint status
    for container in raganything-app raganything-nginx raganything-marker raganything-pg raganything-redis; do
        value=$(docker inspect "$container" --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.RestartCount}}' 2>/dev/null || true)
        [[ -n "$value" ]] || die "required production container is unavailable: $container"
        python3 - "$output" "$container" "$value" <<'PY'
import json
import sys
path, name, value = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)
payload["containers"][name] = value.split()
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, sort_keys=True)
PY
    done
    for endpoint in http://127.0.0.1/api/live http://127.0.0.1/api/ready; do
        status=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --max-time 5 "$endpoint" || true)
        python3 - "$output" "$endpoint" "$status" <<'PY'
import json
import sys
path, endpoint, status = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)
payload["endpoints"][endpoint] = status
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, sort_keys=True)
PY
        [[ "$status" == "200" ]] || die "production health probe failed: $endpoint"
    done
    for container in raganything-app raganything-marker; do
        value=$(docker inspect "$container" --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.RestartCount}}' 2>/dev/null || true)
        [[ "$value" == healthy\ healthy\ 0 || "$value" == running\ healthy\ 0 ]] || die "production container health probe failed: $container"
    done
}

wait_for_test_ready() {
    local base_url=$1 attempts=0 status
    while (( attempts < 36 )); do
        status=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --max-time 5 "$base_url/api/ready" || true)
        [[ "$status" == "200" ]] && return 0
        sleep 5
        ((attempts += 1))
    done
    return 1
}

copy_sanitized_report() {
    local destination="$report_root/$(manifest_value run_id).json"
    mkdir -p "$report_root"
    python3 - "$run_dir/manifest.json" "$destination" <<'PY'
import json
import sys

source, destination = sys.argv[1:]
with open(source, encoding="utf-8") as handle:
    manifest = json.load(handle)
allowed = (
    "run_id", "project", "profile", "app_image_source", "app_image_id",
    "app_image_digest", "marker_image_id", "nginx_image_id", "postgres_image_id",
    "redis_image_id", "free_memory_gib", "free_disk_gib", "resources",
    "diagnostic_mode", "cpu_stop_percent", "cpu_emergency_percent",
    "production_probe_before", "production_probe_after", "cpu_profile",
    "resource_profile", "profile_b_stage", "app_cpu_quota",
    "app_memory_quota_bytes", "runner_sha256", "compose_sha256",
    "fixture_text_sha256", "profile_b_config_sha256", "profile_b_result", "cleanup_verified",
    "profile_b_execution_mode", "profile_b_predecessor_evidence",
)
payload = {key: manifest[key] for key in allowed if key in manifest}
with open(destination, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, sort_keys=True, indent=2)
PY
    printf 'sanitized-report=%s\n' "$destination"
}

validate_profile_b_predecessor() {
    local expected_stage=$1 predecessor=$2 report_root_resolved predecessor_resolved
    report_root_resolved=$(realpath -m "$report_root")
    predecessor_resolved=$(realpath -m "$predecessor")
    [[ "$predecessor_resolved" == "$report_root_resolved"/* ]] || die "Profile B predecessor must be a sanitized report"
    python3 - "$predecessor_resolved" "$expected_stage" "$profile_b_config_sha256" <<'PY'
import json
import sys

path, expected, expected_config = sys.argv[1:]
previous = {5: 1, 10: 5, 20: 10, 30: 20, 40: 30, 50: 40}[int(expected)]
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)
result = payload.get("profile_b_result") or {}
if payload.get("resource_profile") != "profile-b" or payload.get("profile_b_stage") != previous:
    raise SystemExit("predecessor profile/stage mismatch")
if payload.get("profile_b_config_sha256") != expected_config:
    raise SystemExit("predecessor Profile B configuration mismatch")
if result.get("classification") != "profile_b_stage_passed" or not result.get("recovery_passed") or not payload.get("cleanup_verified"):
    raise SystemExit("predecessor lacks pass, recovery, or cleanup evidence")
PY
}

owned_app_container() {
    local project run_id containers container labels
    project=$(manifest_value project)
    run_id=$(manifest_value run_id)
    containers=$(docker ps -q --filter "label=com.docker.compose.project=$project" --filter "label=com.docker.compose.service=app")
    [[ $(printf '%s\n' "$containers" | sed '/^$/d' | wc -l) -eq 1 ]] || die "expected exactly one owned app container"
    container=$(printf '%s\n' "$containers" | sed '/^$/d')
    labels=$(docker inspect "$container" --format '{{ index .Config.Labels "com.docker.compose.project" }} {{ index .Config.Labels "raganything.perf.run-id" }}')
    python3 "$repo_root/scripts/cloud_perf_manifest.py" assert-ownership "$project" "$run_id" "$labels" || die "refusing profile: app ownership mismatch"
    printf '%s\n' "$container"
}

record_owned_resources() {
    local project run_id containers volumes networks
    project=$(manifest_value project)
    run_id=$(manifest_value run_id)
    containers=$(docker ps -aq --filter "label=com.docker.compose.project=$project" --filter "label=raganything.perf.run-id=$run_id")
    volumes=$(docker volume ls -q --filter "label=com.docker.compose.project=$project" --filter "label=raganything.perf.run-id=$run_id")
    networks=$(docker network ls -q --filter "label=com.docker.compose.project=$project" --filter "label=raganything.perf.run-id=$run_id")
    python3 - "$run_dir/manifest.json" "$containers" "$volumes" "$networks" <<'PY'
import json
import sys
path, containers, volumes, networks = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    manifest = json.load(handle)
manifest["resources"] = {
    "containers": containers.split(),
    "volumes": volumes.split(),
    "networks": networks.split(),
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, sort_keys=True)
PY
}

manifest_resources() {
    python3 - "$run_dir/manifest.json" "$1" <<'PY'
import json
import sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
print("\n".join(manifest.get("resources", {}).get(sys.argv[2], [])))
PY
}

assert_owned_resources() {
    local project run_id kind resource labels
    project=$(manifest_value project)
    run_id=$(manifest_value run_id)
    for kind in containers volumes networks; do
      while IFS= read -r resource; do
        [[ -z "$resource" ]] && continue
        case "$kind" in
          containers) labels=$(docker inspect "$resource" --format '{{ index .Config.Labels "com.docker.compose.project" }} {{ index .Config.Labels "raganything.perf.run-id" }}') ;;
          volumes) labels=$(docker volume inspect "$resource" --format '{{ index .Labels "com.docker.compose.project" }} {{ index .Labels "raganything.perf.run-id" }}') ;;
          networks) labels=$(docker network inspect "$resource" --format '{{ index .Labels "com.docker.compose.project" }} {{ index .Labels "raganything.perf.run-id" }}') ;;
        esac
        python3 "$repo_root/scripts/cloud_perf_manifest.py" assert-ownership "$project" "$run_id" "$labels" || die "refusing cleanup: $kind ownership mismatch"
      done < <(manifest_resources "$kind")
    done
}

assert_owned_resources_removed() {
    local kind resource
    for kind in containers volumes networks; do
      while IFS= read -r resource; do
        [[ -z "$resource" ]] && continue
        case "$kind" in
          containers) ! docker container inspect "$resource" >/dev/null 2>&1 || die "cleanup left owned container" ;;
          volumes) ! docker volume inspect "$resource" >/dev/null 2>&1 || die "cleanup left owned volume" ;;
          networks) ! docker network inspect "$resource" >/dev/null 2>&1 || die "cleanup left owned network" ;;
        esac
      done < <(manifest_resources "$kind")
    done
}

owned_resources_are_absent() {
    local kind resource
    for kind in containers volumes networks; do
      while IFS= read -r resource; do
        [[ -z "$resource" ]] && continue
        case "$kind" in
          containers) docker container inspect "$resource" >/dev/null 2>&1 && return 1 ;;
          volumes) docker volume inspect "$resource" >/dev/null 2>&1 && return 1 ;;
          networks) docker network inspect "$resource" >/dev/null 2>&1 && return 1 ;;
        esac
      done < <(manifest_resources "$kind")
    done
    return 0
}

assert_no_active_profile_b_stack() {
    local resource project
    while IFS= read -r resource; do
        [[ -z "$resource" ]] && continue
        project=$(docker inspect "$resource" --format '{{ index .Config.Labels "com.docker.compose.project" }}')
        [[ -n "$project" && "$project" != "<no value>" ]] || die "Profile B stack ownership is incomplete"
        die "another Profile B isolated stack is still active"
    done < <(docker ps -q --filter 'label=raganything.perf.resource-profile=profile-b')
}

case "$phase" in
  preflight)
    require docker
    [[ -n "$app_image" ]] || die "PERF_APP_IMAGE is required"
    app_image=$(resolve_image_id "$app_image")
    [[ "$resource_profile" == profile-a || "$resource_profile" == profile-b ]] || die "PERF_RESOURCE_PROFILE must be profile-a or profile-b"
    if [[ "$resource_profile" == profile-b ]]; then
        if [[ "$profile_b_8c32g_direct" == true ]]; then
            [[ "${PERF_PROFILE_B_AUTHORIZATION:-}" == profile-b-8cpu-24g-direct-50 ]] || die "8C32G Profile B direct diagnostic requires explicit authorization"
            [[ "${PERF_PROFILE_B_DIRECT_AUTHORIZATION:-}" == profile-b-direct-50-8cpu-24g ]] || die "8C32G Profile B direct diagnostic requires direct authorization"
        else
            [[ "${PERF_PROFILE_B_AUTHORIZATION:-}" == profile-b-4cpu-6g-ladder ]] || die "Profile B requires explicit authorization"
        fi
        [[ "$profile_b_stage" == 1 || "$profile_b_stage" == 5 || "$profile_b_stage" == 10 || "$profile_b_stage" == 20 || "$profile_b_stage" == 30 || "$profile_b_stage" == 40 || "$profile_b_stage" == 50 ]] || die "PERF_PROFILE_B_STAGE must be 1, 5, 10, 20, 30, 40, or 50"
        assert_no_active_profile_b_stack
    fi
    preflight_key=$(secret)
    # Import-time setup creates the legacy relative workflows directory.  Keep
    # every preflight write on tmpfs so the immutable image remains read-only.
    if ! docker run --rm --network none --read-only \
      --tmpfs /tmp:rw,noexec,nosuid,size=32m \
      --tmpfs /app/workflows:rw,nosuid,size=1m \
      -e RAGANYTHING_ENV=performance -e LOG_DIR=/tmp/logs -e WORKING_DIR=/tmp/rag_storage \
      -e RUNTIME_SETTINGS_FILE=/tmp/runtime_settings.json \
      -e PERF_CPU_PROFILING=1 -e PERF_CPU_PROFILE_KEY="$preflight_key" \
      -e PERF_SSE_PHASE_ATTRIBUTION="$sse_phase_attribution" -e PYTHONDONTWRITEBYTECODE=1 \
      --entrypoint python "$app_image" -c 'import py_compile; py_compile.compile("/app/server.py", cfile="/tmp/server.pyc", doraise=True); py_compile.compile("/app/raganything/routers/agent.py", cfile="/tmp/agent.pyc", doraise=True); import server; routes = [route for route in server.app.routes if getattr(route, "path", "") == "/api/internal/perf/cpu-profile/{action}"]; assert len(routes) == 1 and set(routes[0].methods or ()) == {"POST"}' >/dev/null 2>&1; then
        die "test image preflight failed"
    fi
    printf 'test-image-preflight=passed\n'
    ;;
  up)
    progress up_start
    require docker
    require python3
    require od
    require curl
    [[ -f "$compose_file" ]] || die "missing Compose profile"
    [[ -n "$app_image" ]] || die "PERF_APP_IMAGE is required"
    [[ "$rate_limit_mode" == enforced || "$rate_limit_mode" == capacity ]] || die "PERF_RATE_LIMIT_MODE must be enforced or capacity"
    [[ "$cpu_profiling" == 0 || "$cpu_profiling" == 1 ]] || die "PERF_ENABLE_CPU_PROFILE must be 0 or 1"
    [[ "$sse_phase_attribution" == 0 || "$sse_phase_attribution" == 1 ]] || die "PERF_SSE_PHASE_ATTRIBUTION must be 0 or 1"
    [[ "$resource_profile" == profile-a || "$resource_profile" == profile-b ]] || die "PERF_RESOURCE_PROFILE must be profile-a or profile-b"
    [[ "$diagnostic_mode" == standard || "$diagnostic_mode" == authorized-20vu || "$diagnostic_mode" == authorized-30-40-50-ladder || "$diagnostic_mode" == profile-b ]] || die "unsupported diagnostic mode"
    cpu_stop_percent=85
    cpu_emergency_percent=200
    app_cpus=2.0
    app_mem_limit=3g
    app_memory_quota_bytes=$((3 * 1024 * 1024 * 1024))
    app_max_async=1
    if [[ "$diagnostic_mode" == authorized-20vu ]]; then
        [[ "${PERF_DIAGNOSTIC_AUTHORIZATION:-}" == authorized-higher-concurrency ]] || die "authorized diagnostic mode requires PERF_DIAGNOSTIC_AUTHORIZATION"
        cpu_stop_percent=170
        cpu_emergency_percent=190
    fi
    if [[ "$diagnostic_mode" == authorized-30-40-50-ladder ]]; then
        [[ "${PERF_DIAGNOSTIC_AUTHORIZATION:-}" == authorized-30-40-50-ladder ]] || die "authorized ladder mode requires PERF_DIAGNOSTIC_AUTHORIZATION"
        [[ "$diagnostic_stage" == 30 || "$diagnostic_stage" == 40 || "$diagnostic_stage" == 50 ]] || die "PERF_DIAGNOSTIC_STAGE must be 30, 40, or 50"
        cpu_stop_percent=170
        cpu_emergency_percent=190
    fi
    if [[ "$resource_profile" == profile-b ]]; then
        [[ "$diagnostic_mode" == profile-b ]] || die "Profile B must use PERF_DIAGNOSTIC_MODE=profile-b"
        if [[ "$profile_b_8c32g_direct" == true ]]; then
            [[ "${PERF_PROFILE_B_AUTHORIZATION:-}" == profile-b-8cpu-24g-direct-50 ]] || die "8C32G Profile B direct diagnostic requires explicit authorization"
        else
            [[ "${PERF_PROFILE_B_AUTHORIZATION:-}" == profile-b-4cpu-6g-ladder ]] || die "Profile B requires explicit authorization"
        fi
        [[ "$profile_b_stage" == 1 || "$profile_b_stage" == 5 || "$profile_b_stage" == 10 || "$profile_b_stage" == 20 || "$profile_b_stage" == 30 || "$profile_b_stage" == 40 || "$profile_b_stage" == 50 ]] || die "PERF_PROFILE_B_STAGE must be 1, 5, 10, 20, 30, or 50"
        [[ "$rate_limit_mode" == capacity && "$cpu_profiling" == 0 && "$sse_phase_attribution" == 0 ]] || die "Profile B requires capacity mode with profiling disabled"
        if [[ "$profile_b_8c32g_direct" == true ]]; then
            app_cpus=8.0
            app_mem_limit=24g
            app_memory_quota_bytes=$((24 * 1024 * 1024 * 1024))
            app_max_async=8
        else
            app_cpus=4.0
            app_mem_limit=6g
            app_memory_quota_bytes=$((6 * 1024 * 1024 * 1024))
            app_max_async=$profile_b_max_async
        fi
        cpu_stop_percent=75
        cpu_emergency_percent=90
    fi
    [[ $(docker context show) != "" ]] || die "Docker context is unavailable"
    progress up_image_resolve
    app_image_source=$app_image
    app_image=$(resolve_image_id "$app_image")
    marker_image=$(resolve_image_id "$marker_image")
    nginx_image=$(resolve_image_id "$nginx_image")
    postgres_image=$(resolve_image_id "$postgres_image")
    redis_image=$(resolve_image_id "$redis_image")
    runner_sha256=$(sha256sum "$repo_root/scripts/run_isolated_cloud_perf.sh" | awk '{print $1}')
    compose_sha256=$(sha256sum "$compose_file" | awk '{print $1}')
    fixture_text_sha256=$(sha256sum "$repo_root/tests/perf/fixtures/sample.txt" | awk '{print $1}')
    profile_b_config_sha256=$(python3 - "$resource_profile" "$app_cpus" "$app_mem_limit" "$app_max_async" "$app_image" "$compose_sha256" <<'PY'
import hashlib
import json
import sys

resource_profile, app_cpus, app_mem_limit, app_max_async, app_image, compose_sha256 = sys.argv[1:]
if resource_profile != "profile-b":
    print("")
else:
    payload = {
        "app_cpu_quota": app_cpus,
        "app_image_id": app_image,
        "app_max_async": app_max_async,
        "app_memory_limit": app_mem_limit,
        "compose_sha256": compose_sha256,
        "mock_token_count": 16,
        "mock_token_interval_ms": 20,
        "mock_ttft_ms": 100,
        "server_workers": 1,
    }
    print(hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest())
PY
)
    if [[ "$resource_profile" == profile-b ]]; then
        [[ "$profile_b_execution_mode" == ordered-ladder || "$profile_b_execution_mode" == direct-50-diagnostic ]] || die "unsupported Profile B execution mode"
        if [[ "$profile_b_execution_mode" == direct-50-diagnostic ]]; then
            [[ "$profile_b_stage" == 50 && -z "$profile_b_predecessor" ]] || die "direct Profile B diagnostic requires stage 50 without predecessor"
            [[ "${PERF_PROFILE_B_DIRECT_AUTHORIZATION:-}" == profile-b-direct-50-8cpu-24g ]] || die "direct Profile B diagnostic requires explicit authorization"
            profile_b_predecessor_evidence=absent_by_authorized_direct_diagnostic
        elif [[ "$profile_b_stage" != 1 ]]; then
            [[ -n "$profile_b_predecessor" && -f "$profile_b_predecessor" ]] || die "Profile B later stages require predecessor evidence"
            validate_profile_b_predecessor "$profile_b_stage" "$profile_b_predecessor"
            profile_b_predecessor_evidence=verified_ordered_predecessor
        else
            profile_b_predecessor_evidence=not_required_first_stage
        fi
    fi
    [[ $(awk '/MemAvailable:/ { print int($2 / 1048576) }' /proc/meminfo) -ge 16 ]] || die "need at least 16 GiB available memory"
    [[ $(df -Pk "$temp_root" | awk 'NR == 2 { print int($4 / 1048576) }') -ge 40 ]] || die "need at least 40 GiB free disk"
    progress up_prepare_run
    run_dir=${run_dir:-$(new_run_dir)}
    assert_child_of_tmp "$run_dir"
    [[ ! -e "$run_dir" ]] || die "run directory already exists"
    umask 077
    mkdir -p "$run_dir"
    mkdir -m 700 "$run_dir/profile"
    cp "$repo_root/tests/perf/mock_provider.py" "$run_dir/mock_provider.py"
    printf '%s\n' 'CREATE EXTENSION IF NOT EXISTS vector;' >"$run_dir/pgvector-init.sql"
    chmod 0644 "$run_dir/pgvector-init.sql"
    local_port=$(unused_loopback_port)
    run_id=$(basename "$run_dir" | sed 's/^raganything-cloud-perf-//')
    project="ragcloudperf-${run_id}"
    write_production_probe "$run_dir/production-before.json" before
    image_digest=$(docker image inspect "$app_image" --format '{{index .RepoDigests 0}}')
    [[ -n "$image_digest" && "$image_digest" != "<no value>" ]] || image_digest=$(docker image inspect "$app_image" --format '{{.Id}}')
    isolated_rate_limit=''
    [[ "$rate_limit_mode" == capacity ]] && isolated_rate_limit='10000/minute'
    cat >"$run_dir/compose.env" <<EOF
PERF_RUN_DIR=$run_dir
PERF_RUN_ID=$run_id
PERF_APP_IMAGE=$app_image
PERF_MARKER_IMAGE=$marker_image
PERF_NGINX_IMAGE=$nginx_image
PERF_POSTGRES_IMAGE=$postgres_image
PERF_REDIS_IMAGE=$redis_image
PERF_HTTP_PORT=$local_port
POSTGRES_USER=perf
POSTGRES_PASSWORD=$(secret)
POSTGRES_DATABASE=perf_${run_id:0:12}
JWT_SECRET=$(secret)
JWT_REFRESH_SECRET=$(secret)
DEFAULT_ADMIN_USERNAME=perf_admin
DEFAULT_ADMIN_PASSWORD=P!$(secret)a9
PERF_MOCK_TTFT_MS=100
PERF_MOCK_TOKEN_INTERVAL_MS=20
PERF_MOCK_TOKEN_COUNT=16
PERF_APP_MAX_ASYNC=$app_max_async
PERF_RATE_LIMIT_MODE=$rate_limit_mode
PERF_ISOLATED_RATE_LIMIT=$isolated_rate_limit
PERF_CPU_PROFILING=$cpu_profiling
PERF_SSE_PHASE_ATTRIBUTION=$sse_phase_attribution
PERF_PROFILE_DIR=$run_dir/profile
PERF_CPU_PROFILE_KEY=$(secret)
PERF_DIAGNOSTIC_MODE=$diagnostic_mode
PERF_CPU_STOP_PERCENT=$cpu_stop_percent
PERF_CPU_EMERGENCY_PERCENT=$cpu_emergency_percent
PERF_DIAGNOSTIC_STAGE=$diagnostic_stage
PERF_RESOURCE_PROFILE=$resource_profile
PERF_PROFILE_B_STAGE=$profile_b_stage
PERF_APP_CPUS=$app_cpus
PERF_APP_MEM_LIMIT=$app_mem_limit
EOF
    db_password=$(awk -F= '$1 == "POSTGRES_PASSWORD" { print $2 }' "$run_dir/compose.env")
    printf 'DATABASE_URL=postgresql://perf:%s@postgres:5432/perf_%s\n' "$db_password" "${run_id:0:12}" >>"$run_dir/compose.env"
    python3 - "$run_dir/manifest.json" "$run_id" "$project" "$app_image_source" "$app_image" "$image_digest" "$marker_image" "$nginx_image" "$postgres_image" "$redis_image" "$local_port" "$rate_limit_mode" "$cpu_profiling" "$diagnostic_mode" "$diagnostic_stage" "$cpu_stop_percent" "$cpu_emergency_percent" "$(free_memory_gib)" "$(free_disk_gib)" "$resource_profile" "$profile_b_stage" "$profile_b_execution_mode" "${profile_b_predecessor_evidence:-}" "$app_cpus" "$app_memory_quota_bytes" "$app_max_async" "$profile_b_config_sha256" "$runner_sha256" "$compose_sha256" "$fixture_text_sha256" <<'PY'
import json
import sys
path, run_id, project, image_source, image_id, digest, marker_id, nginx_id, postgres_id, redis_id, port, rate_limit_mode, cpu_profiling, diagnostic_mode, diagnostic_stage, cpu_stop_percent, cpu_emergency_percent, memory, disk, resource_profile, profile_b_stage, profile_b_execution_mode, profile_b_predecessor_evidence, app_cpu_quota, app_memory_quota_bytes, app_max_async, profile_b_config_sha256, runner_sha256, compose_sha256, fixture_text_sha256 = sys.argv[1:]
payload = {
    "run_id": run_id, "project": project, "app_image_source": image_source,
    "app_image_id": image_id, "app_image_digest": digest,
    "marker_image_id": marker_id, "nginx_image_id": nginx_id,
    "postgres_image_id": postgres_id, "redis_image_id": redis_id,
    "loopback_port": int(port),
    "metrics_url": f"http://127.0.0.1:{port}/metrics",
    "rate_limit_mode": rate_limit_mode,
    "cpu_profiling": cpu_profiling == "1",
    "diagnostic_mode": diagnostic_mode,
    "diagnostic_stage": int(diagnostic_stage) if diagnostic_stage else None,
    "cpu_stop_percent": float(cpu_stop_percent),
    "cpu_emergency_percent": float(cpu_emergency_percent),
    "free_memory_gib": float(memory), "free_disk_gib": float(disk),
    "profile": "isolated-cloud-full-stack",
    "resource_profile": resource_profile,
    "profile_b_stage": int(profile_b_stage) if profile_b_stage else None,
    "profile_b_execution_mode": profile_b_execution_mode if resource_profile == "profile-b" else "",
    "profile_b_predecessor_evidence": profile_b_predecessor_evidence if resource_profile == "profile-b" else "",
    "app_cpu_quota": float(app_cpu_quota),
    "app_memory_quota_bytes": int(app_memory_quota_bytes),
    "profile_b_config_sha256": profile_b_config_sha256,
    "runner_sha256": runner_sha256,
    "compose_sha256": compose_sha256,
    "fixture_text_sha256": fixture_text_sha256,
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, sort_keys=True)
PY
    progress up_compose_config
    docker compose --project-name "$project" --env-file "$run_dir/compose.env" -f "$compose_file" config >"$run_dir/compose.rendered.yml"
    grep -q 'host_ip: 127.0.0.1' "$run_dir/compose.rendered.yml" || die "Compose profile must expose loopback only"
    if grep -E '^[[:space:]]*host_ip:' "$run_dir/compose.rendered.yml" | grep -qv '^[[:space:]]*host_ip: 127\.0\.0\.1$'; then
        die "Compose profile contains a non-loopback host listener"
    fi
    ! grep -qE '/app/(server.py|raganything/.*\.py):ro' "$run_dir/compose.rendered.yml" || die "tested app must not mount source"
    progress up_compose_start
    if ! docker compose --project-name "$project" --env-file "$run_dir/compose.env" -f "$compose_file" up -d; then
        record_owned_resources
        assert_owned_resources
        docker compose --project-name "$project" --env-file "$run_dir/compose.env" -f "$compose_file" down --volumes || true
        assert_owned_resources_removed || true
        die "isolated stack failed during startup"
    fi
    record_owned_resources
    if [[ "$resource_profile" == profile-b ]]; then
        app_container=$(owned_app_container)
        actual_limits=$(docker inspect "$app_container" --format '{{.HostConfig.NanoCpus}} {{.HostConfig.Memory}}')
        expected_limits="4000000000 6442450944"
        [[ "$profile_b_8c32g_direct" == true ]] && expected_limits="8000000000 25769803776"
        [[ "$actual_limits" == "$expected_limits" ]] || die "Profile B app resource limits do not match the manifest"
    fi
    if ! wait_for_test_ready "http://127.0.0.1:$local_port"; then
        assert_owned_resources
        docker compose --project-name "$project" --env-file "$run_dir/compose.env" -f "$compose_file" down --volumes
        assert_owned_resources_removed
        die "isolated stack did not reach /api/ready within 180 seconds"
    fi
    printf 'run-directory=%s\n' "$run_dir"
    ;;
  record-profile-b-result)
    [[ -n "$run_dir" ]] || die "PERF_RUN_DIR is required for result recording"
    assert_child_of_tmp "$run_dir"
    [[ -f "$run_dir/manifest.json" && -f "$run_dir/profile-b-result.json" ]] || die "Profile B result is missing"
    python3 - "$run_dir/manifest.json" "$run_dir/profile-b-result.json" <<'PY'
import json
import sys

manifest_path, result_path = sys.argv[1:]
with open(manifest_path, encoding="utf-8") as handle:
    manifest = json.load(handle)
with open(result_path, encoding="utf-8") as handle:
    result = json.load(handle)
required = {"classification", "requests", "successes", "ttft_p95_ms", "total_p95_ms", "recovery_passed"}
if manifest.get("resource_profile") != "profile-b" or not required <= set(result):
    raise SystemExit("invalid Profile B result")
if result["classification"] not in {"profile_b_stage_passed", "profile_b_hard_stop", "profile_b_invalid_or_preflight_failed", "profile_b_direct_diagnostic_completed", "profile_b_direct_diagnostic_hard_stop"}:
    raise SystemExit("invalid Profile B classification")
for forbidden in ("query", "answer", "token", "thread", "credential", "password", "payload"):
    if forbidden in json.dumps(result, sort_keys=True).lower():
        raise SystemExit("Profile B result contains a forbidden field")
manifest["profile_b_result"] = result
with open(manifest_path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, sort_keys=True)
PY
    ;;
  profile)
    require docker
    require python3
    require date
    [[ -n "$run_dir" ]] || die "PERF_RUN_DIR is required for profiling"
    assert_child_of_tmp "$run_dir"
    [[ -f "$run_dir/manifest.json" && -f "$run_dir/compose.env" ]] || die "owned run manifest is missing"
    [[ $(manifest_value cpu_profiling) == True ]] || die "CPU profiling was not enabled before the isolated stack started"
    profile_seconds=${PERF_CPU_PROFILE_SECONDS:-30}
    [[ "$profile_seconds" =~ ^[1-9][0-9]?$ && "$profile_seconds" -le 60 ]] || die "PERF_CPU_PROFILE_SECONDS must be 1-60"
    app_container=$(owned_app_container)
    app_image_id=$(docker inspect "$app_container" --format '{{.Image}}')
    [[ "$app_image_id" == "$(manifest_value app_image_id)" ]] || die "refusing profile: app image does not match manifest"
    run_id=$(manifest_value run_id)
    profile_started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    project=$(manifest_value project)
    profile_error=''
    local_port=$(manifest_value loopback_port)
    profile_key=$(awk -F= '$1 == "PERF_CPU_PROFILE_KEY" { print $2 }' "$run_dir/compose.env")
    [[ -n "$profile_key" ]] || die "profile key is missing from owned runtime configuration"
    curl --silent --show-error --fail --max-time 5 -X POST \
      -H "X-Raganything-Perf-Profile: $profile_key" \
      "http://127.0.0.1:$local_port/api/internal/perf/cpu-profile/start" >/dev/null \
      || profile_error='profiler_start_failed'
    if [[ -z "$profile_error" ]]; then
        sleep "$profile_seconds"
        curl --silent --show-error --fail --max-time 5 -X POST \
          -H "X-Raganything-Perf-Profile: $profile_key" \
          "http://127.0.0.1:$local_port/api/internal/perf/cpu-profile/stop" >/dev/null \
          || profile_error='profiler_stop_failed'
    fi
    profile_finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    if [[ -z "$profile_error" ]] && ! docker cp "$app_container:/tmp/raganything-perf-cpu.pstats" "$run_dir/profile/app-cpu.pstats" >/dev/null 2>&1; then
        profile_error='profiler_output_missing'
    fi
    if [[ -z "$profile_error" && ! -s "$run_dir/profile/app-cpu.pstats" ]]; then
        profile_error='profiler_output_missing'
    fi
    if [[ -z "$profile_error" ]] && ! python3 "$repo_root/scripts/cloud_perf_manifest.py" summarize-cpu-profile \
      --output "$run_dir/cpu-profile.json" --container "$app_container" --run-id "$run_id" --image-id "$app_image_id" \
      --started-at "$profile_started" --finished-at "$profile_finished" --input "$run_dir/profile/app-cpu.pstats"; then
        profile_error='profiler_output_invalid'
    fi
    rm -f "$run_dir/profile/app-cpu.pstats"
    docker exec "$app_container" rm -f /tmp/raganything-perf-cpu.pstats >/dev/null 2>&1 || true
    if [[ -n "$profile_error" ]]; then
      python3 - "$run_dir/cpu-profile.json" "$app_container" "$run_id" "$app_image_id" "$profile_started" "$profile_finished" "${profile_error:-profiler_output_missing}" <<'PY'
import json
import sys
path, container, run_id, image_id, started, finished, error = sys.argv[1:]
with open(path, "w", encoding="utf-8") as handle:
    json.dump({"available": False, "container": container, "run_id": run_id, "app_image_id": image_id, "started_at": started, "finished_at": finished, "error_class": error}, handle, sort_keys=True)
PY
    fi
    python3 - "$run_dir/manifest.json" "$run_dir/cpu-profile.json" <<'PY'
import json
import sys
manifest_path, profile_path = sys.argv[1:]
with open(manifest_path, encoding="utf-8") as handle:
    manifest = json.load(handle)
with open(profile_path, encoding="utf-8") as handle:
    manifest["cpu_profile"] = json.load(handle)
with open(manifest_path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, sort_keys=True)
PY
    printf 'cpu-profile=%s\n' "$run_dir/cpu-profile.json"
    ;;
  down)
    [[ -n "$run_dir" ]] || die "PERF_RUN_DIR is required for cleanup"
    assert_child_of_tmp "$run_dir"
    [[ -f "$run_dir/manifest.json" && -f "$run_dir/compose.env" ]] || die "owned run manifest is missing"
    if ! owned_resources_are_absent; then
        assert_owned_resources
        project=$(manifest_value project)
        docker compose --project-name "$project" --env-file "$run_dir/compose.env" -f "$compose_file" down --volumes
    fi
    assert_owned_resources_removed
    write_production_probe "$run_dir/production-after.json" after
    python3 - "$run_dir/manifest.json" "$run_dir/production-before.json" "$run_dir/production-after.json" <<'PY'
import json
import sys
manifest_path, before_path, after_path = sys.argv[1:]
with open(manifest_path, encoding="utf-8") as handle:
    manifest = json.load(handle)
for target, source in (("production_probe_before", before_path), ("production_probe_after", after_path)):
    with open(source, encoding="utf-8") as handle:
        manifest[target] = json.load(handle)
manifest["cleanup_verified"] = True
with open(manifest_path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, sort_keys=True)
PY
    copy_sanitized_report
    rm -rf -- "$run_dir"
    ;;
  *) die "usage: $0 preflight|up|profile|record-profile-b-result|down (set PERF_APP_IMAGE and optionally PERF_RUN_DIR)" ;;
esac
