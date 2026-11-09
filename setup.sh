#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

MODEL_REPO="bartowski/glm-4-9b-chat-abliterated-GGUF"
BIN_DIR="${BIN_DIR:-${HOME}/.local/bin}"
TARGET="${SCRIPT_DIR}/glm"
LINK="${BIN_DIR}/glm"

usage() {
    cat <<EOF
Usage: setup.sh [--uninstall]

Without arguments, installs everything needed to run 'glm'. Steps that are
already done are skipped, so it is safe to run again:
  1. llama-cpp and a ggml GPU backend via pacman (asks for sudo)
  2. ${MODEL_FILE} from ${MODEL_REPO} (resumes a partial download)
  3. a 'glm' link in ${BIN_DIR}

  --uninstall   Remove the 'glm' link. Packages and the model are kept.

Environment:
  BACKEND      cuda or vulkan (default: cuda if nvidia-smi exists, otherwise vulkan)
  BIN_DIR      Directory for the 'glm' link (default: ~/.local/bin)
  MODEL_PATH   Where the model is stored (default: next to this script)
EOF
}

install_llama_cpp() {
    if ! command -v pacman >/dev/null 2>&1; then
        if command -v llama-server >/dev/null 2>&1 && command -v llama-cli >/dev/null 2>&1; then
            echo "llama.cpp: already installed"
            return
        fi
        echo "Error: llama.cpp is not installed and pacman is not available; install llama.cpp manually." >&2
        exit 1
    fi

    if [[ -z "${BACKEND:-}" ]] && pacman -Q llama-cpp >/dev/null 2>&1 &&
        { pacman -Q ggml-cuda >/dev/null 2>&1 || pacman -Q ggml-vulkan >/dev/null 2>&1; }; then
        echo "llama.cpp: already installed"
        return
    fi

    local backend="${BACKEND:-}"
    if [[ -z "${backend}" ]]; then
        if command -v nvidia-smi >/dev/null 2>&1; then
            backend="cuda"
        else
            backend="vulkan"
        fi
    fi
    if [[ "${backend}" != "cuda" && "${backend}" != "vulkan" ]]; then
        echo "Error: BACKEND must be 'cuda' or 'vulkan', got '${backend}'." >&2
        exit 1
    fi

    if pacman -Q llama-cpp "ggml-${backend}" >/dev/null 2>&1; then
        echo "llama.cpp: already installed with the ${backend} backend"
        return
    fi

    echo "llama.cpp: installing llama-cpp and ggml-${backend} (requires sudo)"
    sudo pacman -S --needed llama-cpp "ggml-${backend}"
}

download_model() {
    if [[ -f "${MODEL_PATH}" ]]; then
        echo "Model: already present at ${MODEL_PATH}"
        return
    fi

    require_binary curl
    local url="https://huggingface.co/${MODEL_REPO}/resolve/main/${MODEL_FILE}"

    echo "Model: downloading ${MODEL_FILE} (~6 GB) to ${MODEL_PATH}"
    mkdir -p "$(dirname "${MODEL_PATH}")"
    if ! curl -fL -C - -o "${MODEL_PATH}.part" "${url}"; then
        echo "Error: Download failed; run setup.sh again to resume it." >&2
        exit 1
    fi
    mv "${MODEL_PATH}.part" "${MODEL_PATH}"
}

is_our_link() {
    [[ -L "${LINK}" && "$(readlink -f "${LINK}")" == "${TARGET}" ]]
}

link_command() {
    if is_our_link; then
        echo "Command: already linked at ${LINK}"
    elif [[ -e "${LINK}" || -L "${LINK}" ]]; then
        echo "Error: ${LINK} already exists and does not point to ${TARGET}; not overwriting." >&2
        exit 1
    else
        mkdir -p "${BIN_DIR}"
        ln -s "${TARGET}" "${LINK}"
        echo "Command: linked ${LINK} -> ${TARGET}"
    fi

    case ":${PATH}:" in
        *":${BIN_DIR}:"*) ;;
        *) echo "Warning: ${BIN_DIR} is not in PATH; add it to run 'glm' from any directory." >&2 ;;
    esac
}

unlink_command() {
    if is_our_link; then
        rm "${LINK}"
        echo "Command: removed ${LINK}"
    else
        echo "Error: ${LINK} is not a link to ${TARGET}; nothing removed." >&2
        exit 1
    fi
}

case "${1:-}" in
    "")
        install_llama_cpp
        download_model
        link_command
        echo "Setup complete. Start with 'glm server' or 'glm cli'."
        ;;
    --uninstall) unlink_command ;;
    -h | --help) usage ;;
    *)
        usage >&2
        exit 1
        ;;
esac
