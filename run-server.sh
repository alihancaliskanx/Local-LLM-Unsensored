#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

PARALLEL_SLOTS="${PARALLEL:-1}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8080}"

require_model
require_binary llama-server
wait_for_gpu

exec llama-server \
    "${COMMON_ARGS[@]}" \
    --log-disable \
    -np "${PARALLEL_SLOTS}" \
    --host "${HOST}" \
    --port "${PORT}" \
    "$@"
