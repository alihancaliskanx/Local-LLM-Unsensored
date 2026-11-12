#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

RULES_PATH="${RULES_PATH:-${SCRIPT_DIR}/cli_rules.md}"

require_model
require_binary llama-cli
wait_for_gpu

EXTRA_ARGS=()
if [[ -f "${RULES_PATH}" ]]; then
    EXTRA_ARGS+=(-sysf "${RULES_PATH}")
fi

exec llama-cli \
    "${COMMON_ARGS[@]}" \
    "${EXTRA_ARGS[@]}" \
    "$@"
