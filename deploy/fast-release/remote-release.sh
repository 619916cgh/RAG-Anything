#!/usr/bin/env bash
set -Eeuo pipefail

# Invoked by deploy.ps1 after it has staged a complete committed payload.
# Arguments are deliberately positional so the caller can keep the remote
# command simple and the script can validate every operational boundary.
if [[ $# -ne 13 ]]; then
    echo "usage: remote-release.sh COMMIT ARCHIVE SHA PROJECT RELEASE_ROOT APP_RUNTIME APP_RUNTIME_ID NGINX_RUNTIME NGINX_RUNTIME_ID MIN_FREE_GB HEALTH_WINDOW HEALTH_INTERVAL MANIFEST" >&2
    exit 64
fi

commit="$1"
archive="$2"
expected_archive_sha="$3"
project_dir="$4"
release_root="$5"
app_runtime_image="$6"
app_runtime_id="$7"
nginx_runtime_image="$8"
nginx_runtime_id="$9"
minimum_free_gb="${10}"
health_window_seconds="${11}"
health_interval_seconds="${12}"
input_manifest="${13}"

for value in "$commit" "$expected_archive_sha" "$app_runtime_id" "$nginx_runtime_id"; do
    [[ "$value" =~ ^(sha256:)?[0-9a-f]{40,64}$ ]] || {
        echo "Unsafe commit, checksum, or image identifier." >&2
        exit 64
    }
done
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo "Commit must be a full SHA." >&2; exit 64; }
[[ "$expected_archive_sha" =~ ^[0-9a-f]{64}$ ]] || { echo "Payload checksum must be SHA-256." >&2; exit 64; }
[[ "$app_runtime_id" =~ ^sha256:[0-9a-f]{64}$ && "$nginx_runtime_id" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    echo "Runtime image IDs must be immutable sha256 identifiers." >&2
    exit 64
}
[[ "$project_dir" =~ ^/[A-Za-z0-9._/-]+$ && "$release_root" =~ ^/[A-Za-z0-9._/-]+$ ]] || {
    echo "Unsafe project or release directory." >&2
    exit 64
}
[[ "$minimum_free_gb" =~ ^[0-9]+$ && "$health_window_seconds" =~ ^[1-9][0-9]*$ && "$health_interval_seconds" =~ ^[1-9][0-9]*$ ]] || {
    echo "Invalid capacity or health-window configuration." >&2
    exit 64
}
[[ -f "$archive" && -f "$input_manifest" && -d "$project_dir" ]] || {
    echo "Required release inputs are missing." >&2
    exit 66
}
grep -Eq "\"commit_sha\"[[:space:]]*:[[:space:]]*\"$commit\"" "$input_manifest" || {
    echo "Release manifest commit does not match the requested release." >&2
    exit 65
}
grep -Eq "\"payload_sha256\"[[:space:]]*:[[:space:]]*\"$expected_archive_sha\"" "$input_manifest" || {
    echo "Release manifest checksum does not match the requested release." >&2
    exit 65
}

exec 9>/var/lock/raganything-fast-release.lock
flock -n 9 || { echo "Another fast release already holds the host lock." >&2; exit 75; }

if ps -eo args | grep -qE '[d]ocker (build|compose build)|[d]ocker-compose .*build'; then
    echo "An active Docker build was found; release will not compete for host capacity." >&2
    exit 75
fi

available_gb=$(( $(df -Pk / | awk 'NR==2 { print int($4 / 1024 / 1024) }') ))
if (( available_gb < minimum_free_gb )); then
    echo "Insufficient free disk: ${available_gb}GB available, ${minimum_free_gb}GB required." >&2
    exit 75
fi

actual_archive_sha="$(sha256sum "$archive" | awk '{print $1}')"
[[ "$actual_archive_sha" == "$expected_archive_sha" ]] || { echo "Payload checksum mismatch." >&2; exit 65; }
tar -tzf "$archive" | awk 'BEGIN { valid = 1 } $0 !~ /^payload\// || $0 ~ /(^|\/)\.\.\// { valid = 0 } END { exit !valid }' || {
    echo "Release archive contains an unsafe path." >&2
    exit 65
}

actual_app_runtime_id="$(docker image inspect "$app_runtime_image" --format '{{.Id}}')"
actual_nginx_runtime_id="$(docker image inspect "$nginx_runtime_image" --format '{{.Id}}')"
[[ "$actual_app_runtime_id" == "$app_runtime_id" ]] || { echo "Configured app runtime tag no longer matches its accepted ID." >&2; exit 65; }
[[ "$actual_nginx_runtime_id" == "$nginx_runtime_id" ]] || { echo "Configured Nginx runtime tag no longer matches its accepted ID." >&2; exit 65; }

release_dir="$release_root/$commit"
if [[ -e "$release_dir" ]]; then
    echo "Release directory already exists for commit $commit." >&2
    exit 73
fi
mkdir -p "$release_root"
mkdir -m 700 "$release_dir"
tar -xzf "$archive" -C "$release_dir"
payload_dir="$release_dir/payload"
[[ -f "$payload_dir/server.py" && -f "$payload_dir/frontend/dist/index.html" ]] || {
    echo "Release payload is incomplete." >&2
    exit 65
}
[[ -f "$payload_dir/deploy/fast-release/Dockerfile.app" && -f "$payload_dir/deploy/fast-release/Dockerfile.nginx" ]] || {
    echo "Release payload lacks the immutable fast-release build instructions." >&2
    exit 65
}

short_commit="${commit:0:12}"
candidate_app_image="raganything-app:fast-${short_commit}"
candidate_nginx_image="raganything-nginx:fast-${short_commit}"

docker build \
    --build-arg "RUNTIME_IMAGE=$app_runtime_image" \
    --tag "$candidate_app_image" \
    --file "$payload_dir/deploy/fast-release/Dockerfile.app" \
    "$release_dir"
docker build \
    --build-arg "NGINX_RUNTIME_IMAGE=$nginx_runtime_image" \
    --tag "$candidate_nginx_image" \
    --file "$payload_dir/deploy/fast-release/Dockerfile.nginx" \
    "$release_dir"

candidate_app_id="$(docker image inspect "$candidate_app_image" --format '{{.Id}}')"
candidate_nginx_id="$(docker image inspect "$candidate_nginx_image" --format '{{.Id}}')"

compose() {
    (
        cd "$project_dir"
        RAGANYTHING_APP_IMAGE="$1" RAGANYTHING_NGINX_IMAGE="$2" docker compose "${@:3}"
    )
}

# This creates only a disposable app container and imports the modules that
# previously diverged under partial file uploads. It does not invoke migration.
compose "$candidate_app_image" "$candidate_nginx_image" run --rm --no-deps --no-build --entrypoint python app \
    -c 'import server; from raganything.routers import knowledge'

old_app_id="$(docker inspect raganything-app --format '{{.Image}}')"
old_nginx_id="$(docker inspect raganything-nginx --format '{{.Image}}')"
rollback_app_image="raganything-app:fast-rollback-${short_commit}"
rollback_nginx_image="raganything-nginx:fast-rollback-${short_commit}"
docker image tag "$old_app_id" "$rollback_app_image"
docker image tag "$old_nginx_id" "$rollback_nginx_image"

switched=0
accepted=0
rollback() {
    status=$?
    if (( switched == 1 && accepted == 0 )); then
        echo "Release failed after service replacement; restoring app and Nginx." >&2
        compose "$rollback_app_image" "$rollback_nginx_image" up -d --no-deps --no-build --force-recreate app || true
        compose "$rollback_app_image" "$rollback_nginx_image" up -d --no-deps --no-build --force-recreate nginx || true
        curl -fsS --max-time 10 http://127.0.0.1:8000/api/health >/dev/null || true
        curl -fsS --max-time 10 http://127.0.0.1/api/health >/dev/null || true
    fi
    exit "$status"
}
trap rollback ERR INT TERM

assert_direct_health() {
    curl -fsS --max-time 10 http://127.0.0.1:8000/api/health >/dev/null
    [[ "$(docker inspect raganything-app --format '{{.RestartCount}}')" == "0" ]]
}

assert_full_health() {
    assert_direct_health
    curl -fsS --max-time 10 http://127.0.0.1/api/health >/dev/null
}

switched=1
compose "$candidate_app_image" "$candidate_nginx_image" up -d --no-deps --no-build --force-recreate app
assert_direct_health
compose "$candidate_app_image" "$candidate_nginx_image" up -d --no-deps --no-build --force-recreate nginx

deadline=$(( $(date +%s) + health_window_seconds ))
while (( $(date +%s) <= deadline )); do
    assert_full_health
    sleep "$health_interval_seconds"
done

printf '{\n  "commit_sha": "%s",\n  "payload_sha256": "%s",\n  "app_runtime_image": "%s",\n  "app_runtime_id": "%s",\n  "nginx_runtime_image": "%s",\n  "nginx_runtime_id": "%s",\n  "app_image": "%s",\n  "app_image_id": "%s",\n  "nginx_image": "%s",\n  "nginx_image_id": "%s",\n  "rollback_app_image": "%s",\n  "rollback_nginx_image": "%s",\n  "released_utc": "%s"\n}\n' \
    "$commit" "$expected_archive_sha" "$app_runtime_image" "$app_runtime_id" "$nginx_runtime_image" "$nginx_runtime_id" \
    "$candidate_app_image" "$candidate_app_id" "$candidate_nginx_image" "$candidate_nginx_id" \
    "$rollback_app_image" "$rollback_nginx_image" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > "$release_dir/release-manifest.json"

accepted=1
trap - ERR INT TERM
echo "Fast release accepted: $commit"
