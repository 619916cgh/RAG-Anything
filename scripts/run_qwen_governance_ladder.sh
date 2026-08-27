#!/usr/bin/env bash
# Run the isolated Qwen acceptance ladder with one temporary-key prompt.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
image=${1:-raganything-perf-capacity:qwen-govern-profile-20260821-docfix2}
report_root=${2:-/tmp/qwen-govern-reports-docfix2}

read -r -s -p "Temporary Qwen key: " PERF_QWEN_API_KEY
printf '\n'
export PERF_QWEN_API_KEY
export PERF_QWEN_ENDPOINT="https://dashscope.aliyuncs.com/compatible-mode/v1"
export PERF_QWEN_MODEL="qwen-plus"
export PERF_QWEN_EMBEDDING_MODEL="text-embedding-v4"
export PERF_QWEN_QUOTA_RECORD="/tmp/qwen-govern-quota.json"
mkdir -p "$report_root"

cleanup() {
  unset PERF_QWEN_API_KEY PERF_QWEN_ENDPOINT PERF_QWEN_MODEL \
    PERF_QWEN_EMBEDDING_MODEL PERF_QWEN_QUOTA_RECORD
}
trap cleanup EXIT

predecessor=""
for stage in 10 20 30 40 50; do
  command=(
    python3 "$repo_root/scripts/run_profile_b_ladder.py"
    --stage "$stage"
    --app-image "$image"
    --report-root "$report_root"
    --provider-profile qwen
  )
  if [[ -n "$predecessor" ]]; then
    command+=(--predecessor "$predecessor")
  fi
  "${command[@]}"
  predecessor=$(find "$report_root" -maxdepth 1 -type f -name '*.json' -printf '%T@ %p\n' | sort -nr | head -n 1 | cut -d' ' -f2-)
  [[ -n "$predecessor" ]] || { printf '%s\n' 'cloud-perf: stage report was not recorded' >&2; exit 1; }
done
