#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

PARALLEL_SLOTS="${PARALLEL:-1}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8080}"

require_model
require_binary llama-server
wait_for_gpu

PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}" LLAMA_SERVER_URL="http://${HOST}:${PORT}" \
    python3 -m cll.opencode_bridge >/dev/null 2>&1 &
BRIDGE_PID=$!

cleanup() {
    kill "${BRIDGE_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

llama-server \
    "${COMMON_ARGS[@]}" \
    --log-disable \
    -np "${PARALLEL_SLOTS}" \
    --host "${HOST}" \
    --port "${PORT}" \
    "$@"
