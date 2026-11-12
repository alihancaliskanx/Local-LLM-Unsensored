# shellcheck shell=bash

MODEL_FILE="Huihui-Qwen3-4B-Instruct-2507-abliterated.i1-Q4_K_M.gguf"
MODEL_PATH="${MODEL_PATH:-${SCRIPT_DIR}/${MODEL_FILE}}"
GPU_LAYERS="${NGL:-auto}"
FIT_MARGIN="${FIT_TARGET:-512}"
CTX_SIZE="${CTX:-8192}"
THREADS="${THREADS:-6}"

# shellcheck disable=SC2034 # used by the scripts that source this file
COMMON_ARGS=(
    -m "${MODEL_PATH}"
    -ngl "${GPU_LAYERS}"
    -fit on
    -fitt "${FIT_MARGIN}"
    -c "${CTX_SIZE}"
    -fa on
    -ctk q4_0
    -ctv q4_0
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
    echo "Stop it first with: pkill -x '${pattern}'" >&2
    exit 1
}
