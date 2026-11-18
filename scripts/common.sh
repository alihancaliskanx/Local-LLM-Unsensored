# shellcheck shell=bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Resolve active model configuration via model_manager if not explicitly provided
if [[ -z "${MODEL_PATH:-}" ]] && command -v python3 >/dev/null 2>&1; then
    eval "$(PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}" python3 -m cll.model_manager env 2>/dev/null || true)"
fi

MODEL_FILE="Huihui-Qwen3-4B-Instruct-2507-abliterated.i1-Q4_K_M.gguf"
MODEL_PATH="${MODEL_PATH:-${REPO_ROOT}/${MODEL_FILE}}"
GPU_LAYERS="${NGL:-auto}"
FIT_MARGIN="${FIT_TARGET:-768}"
CTX_SIZE="${CTX:-32768}"

# Auto-detect CPU threads for cross-machine compatibility
if [[ -z "${THREADS:-}" ]]; then
    if command -v nproc >/dev/null 2>&1; then
        _CORES="$(nproc)"
        if [[ "${_CORES}" -gt 8 ]]; then
            THREADS=8
        elif [[ "${_CORES}" -gt 0 ]]; then
            THREADS="${_CORES}"
        else
            THREADS=4
        fi
    else
        THREADS=4
    fi
fi

# shellcheck disable=SC2034 # used by the scripts that source this file
COMMON_ARGS=(
    -m "${MODEL_PATH}"
    -ngl "${GPU_LAYERS}"
    -fit on
    -fitt "${FIT_MARGIN}"
    -c "${CTX_SIZE}"
    -fa on
    -ctk q8_0
    -ctv q8_0
    -t "${THREADS}"
)

require_model() {
    if [[ ! -f "${MODEL_PATH}" ]]; then
        echo "Error: Model file not found at ${MODEL_PATH}" >&2
        exit 1
    fi
}

require_binary() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Error: $1 is not installed." >&2
        exit 1
    fi
}

# llama-server and llama-cli each need most of the 4 GB of VRAM, so neither
# may start while another instance of either is running.
wait_for_gpu() {
    local pattern="llama-server|llama-cli"

    pgrep -x "${pattern}" >/dev/null 2>&1 || return 0

    echo "Waiting for running llama.cpp processes to release GPU memory..." >&2
    for _ in {1..5}; do
        pgrep -x "${pattern}" >/dev/null 2>&1 || return 0
        sleep 1
    done

    echo "Error: Another llama.cpp instance is still running and holding VRAM:" >&2
    pgrep -l -x "${pattern}" | sed 's/^/  /' >&2
    echo "Stop it first with: pkill -x '${pattern}' (or pkill -9 -x '${pattern}')" >&2
    exit 1
}
