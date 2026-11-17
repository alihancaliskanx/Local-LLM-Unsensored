#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
# shellcheck source=scripts/common.sh
source "${SCRIPT_DIR}/scripts/common.sh"

MODEL_REPO="mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-i1-GGUF"
COMMAND_NAME="qwen-local"
TORSEARCH_NAME="torsearch"
REAPER_NAME="cll-reaper"
QSTOP_NAME="qstop"
BIN_DIR="${BIN_DIR:-${HOME}/.local/bin}"
MAN_DIR="${MAN_DIR:-${HOME}/.local/share/man/man1}"
TARGET="${REPO_ROOT}/${COMMAND_NAME}"
LINK="${BIN_DIR}/${COMMAND_NAME}"
TORSEARCH_TARGET="${REPO_ROOT}/${TORSEARCH_NAME}"
TORSEARCH_LINK="${BIN_DIR}/${TORSEARCH_NAME}"
REAPER_TARGET="${REPO_ROOT}/tools/cll-reaper/target/release/${REAPER_NAME}"
REAPER_LINK="${BIN_DIR}/${REAPER_NAME}"
QSTOP_TARGET="${REPO_ROOT}/scripts/${QSTOP_NAME}"
QSTOP_LINK="${BIN_DIR}/${QSTOP_NAME}"
LEGACY_LINK="${BIN_DIR}/glm"

usage() {
    cat <<EOF
Usage: setup.sh [--uninstall]

Without arguments, installs everything needed to run '${COMMAND_NAME}'. Steps that are
already done are skipped, so it is safe to run again:
  1. llama-cpp and a ggml GPU backend via pacman (asks for sudo)
  2. ${MODEL_FILE} from ${MODEL_REPO} (resumes a partial download)
  3. '${COMMAND_NAME}', '${TORSEARCH_NAME}', and '${REAPER_NAME}' links in ${BIN_DIR}
  4. manual pages (man1) linked into ${MAN_DIR}

  --uninstall   Remove '${COMMAND_NAME}', '${TORSEARCH_NAME}', '${REAPER_NAME}', and manpage links. Packages and the model are kept.

Environment:
  BACKEND      cuda or vulkan (default: cuda if nvidia-smi exists, otherwise vulkan)
  BIN_DIR      Directory for the '${COMMAND_NAME}' link (default: ~/.local/bin)
  MAN_DIR      Directory for man1 manual pages (default: ~/.local/share/man/man1)
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

    echo "Model: downloading ${MODEL_FILE} (~2.5 GB) to ${MODEL_PATH}"
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

clean_legacy_link() {
    if [[ -L "${LEGACY_LINK}" ]]; then
        local dest
        dest="$(readlink -f "${LEGACY_LINK}")" || true
        if [[ "${dest}" == "${SCRIPT_DIR}/glm" || "${dest}" == "${TARGET}" ]]; then
            rm "${LEGACY_LINK}"
            echo "Command: removed legacy link ${LEGACY_LINK}"
        fi
    fi
    if [[ -L "${LINK}" && ! -e "${LINK}" ]]; then
        rm "${LINK}"
        echo "Command: removed dangling link ${LINK}"
    fi
}

build_reaper() {
    if ! command -v cargo >/dev/null 2>&1; then
        echo "cll-reaper: cargo not found; skipping Rust reaper compilation"
        return 0
    fi
    if [[ -f "${REAPER_TARGET}" ]]; then
        echo "cll-reaper: already built at ${REAPER_TARGET}"
        return 0
    fi
    echo "cll-reaper: compiling minimal Rust daemon in release mode..."
    cargo build --release --manifest-path "${REPO_ROOT}/tools/cll-reaper/Cargo.toml" --quiet
}

link_command() {
    clean_legacy_link
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

    if [[ -L "${TORSEARCH_LINK}" && "$(readlink -f "${TORSEARCH_LINK}")" == "${TORSEARCH_TARGET}" ]]; then
        echo "Command: already linked at ${TORSEARCH_LINK}"
    elif [[ -e "${TORSEARCH_LINK}" || -L "${TORSEARCH_LINK}" ]]; then
        ln -sf "${TORSEARCH_TARGET}" "${TORSEARCH_LINK}"
        echo "Command: linked ${TORSEARCH_LINK} -> ${TORSEARCH_TARGET}"
    else
        mkdir -p "${BIN_DIR}"
        ln -s "${TORSEARCH_TARGET}" "${TORSEARCH_LINK}"
        echo "Command: linked ${TORSEARCH_LINK} -> ${TORSEARCH_TARGET}"
    fi

    if [[ -f "${REAPER_TARGET}" ]]; then
        if [[ -L "${REAPER_LINK}" && "$(readlink -f "${REAPER_LINK}")" == "${REAPER_TARGET}" ]]; then
            echo "Command: already linked at ${REAPER_LINK}"
        elif [[ -e "${REAPER_LINK}" || -L "${REAPER_LINK}" ]]; then
            ln -sf "${REAPER_TARGET}" "${REAPER_LINK}"
            echo "Command: linked ${REAPER_LINK} -> ${REAPER_TARGET}"
        else
            mkdir -p "${BIN_DIR}"
            ln -s "${REAPER_TARGET}" "${REAPER_LINK}"
            echo "Command: linked ${REAPER_LINK} -> ${REAPER_TARGET}"
        fi
    fi

    if [[ -f "${QSTOP_TARGET}" ]]; then
        if [[ -L "${QSTOP_LINK}" && "$(readlink -f "${QSTOP_LINK}")" == "${QSTOP_TARGET}" ]]; then
            echo "Command: already linked at ${QSTOP_LINK}"
        elif [[ -e "${QSTOP_LINK}" || -L "${QSTOP_LINK}" ]]; then
            ln -sf "${QSTOP_TARGET}" "${QSTOP_LINK}"
            echo "Command: linked ${QSTOP_LINK} -> ${QSTOP_TARGET}"
        else
            mkdir -p "${BIN_DIR}"
            ln -s "${QSTOP_TARGET}" "${QSTOP_LINK}"
            echo "Command: linked ${QSTOP_LINK} -> ${QSTOP_TARGET}"
        fi
    fi

    case ":${PATH}:" in
        *":${BIN_DIR}:"*) ;;
        *) echo "Warning: ${BIN_DIR} is not in PATH; add it to run '${COMMAND_NAME}' from any directory." >&2 ;;
    esac
}

link_man_pages() {
    local src_dir="${REPO_ROOT}/man/man1"
    if [[ -d "${src_dir}" ]]; then
        mkdir -p "${MAN_DIR}"
        for manfile in "${src_dir}"/*.1; do
            [[ -f "${manfile}" ]] || continue
            local base
            base="$(basename "${manfile}")"
            local dest="${MAN_DIR}/${base}"
            ln -sf "${manfile}" "${dest}"
            echo "Manpage: linked ${dest} -> ${manfile}"
        done
    fi
}

unlink_man_pages() {
    local src_dir="${REPO_ROOT}/man/man1"
    if [[ -d "${src_dir}" && -d "${MAN_DIR}" ]]; then
        for manfile in "${src_dir}"/*.1; do
            [[ -f "${manfile}" ]] || continue
            local base
            base="$(basename "${manfile}")"
            local dest="${MAN_DIR}/${base}"
            if [[ -L "${dest}" && "$(readlink -f "${dest}")" == "$(readlink -f "${manfile}")" ]]; then
                rm -f "${dest}"
                echo "Manpage: removed link ${dest}"
            fi
        done
    fi
}

unlink_command() {
    local removed=0
    if is_our_link; then
        rm "${LINK}"
        echo "Command: removed ${LINK}"
        removed=1
    fi
    if [[ -L "${TORSEARCH_LINK}" && "$(readlink -f "${TORSEARCH_LINK}")" == "${TORSEARCH_TARGET}" ]]; then
        rm "${TORSEARCH_LINK}"
        echo "Command: removed ${TORSEARCH_LINK}"
        removed=1
    fi
    if [[ -L "${REAPER_LINK}" && "$(readlink -f "${REAPER_LINK}")" == "${REAPER_TARGET}" ]]; then
        rm "${REAPER_LINK}"
        echo "Command: removed ${REAPER_LINK}"
        removed=1
    fi
    if [[ -L "${QSTOP_LINK}" && "$(readlink -f "${QSTOP_LINK}")" == "${QSTOP_TARGET}" ]]; then
        rm "${QSTOP_LINK}"
        echo "Command: removed ${QSTOP_LINK}"
        removed=1
    fi
    if [[ -L "${LEGACY_LINK}" ]]; then
        local dest
        dest="$(readlink -f "${LEGACY_LINK}")" || true
        if [[ "${dest}" == "${REPO_ROOT}/glm" || "${dest}" == "${TARGET}" ]]; then
            rm "${LEGACY_LINK}"
            echo "Command: removed legacy link ${LEGACY_LINK}"
            removed=1
        fi
    fi
    if [[ "${removed}" -eq 0 ]]; then
        echo "Error: Neither ${LINK} nor ${LEGACY_LINK} points to this repository; nothing removed." >&2
        exit 1
    fi
}

case "${1:-}" in
    "")
        install_llama_cpp
        download_model
        build_reaper
        link_command
        link_man_pages
        echo "Setup complete. Start with '${COMMAND_NAME} server' or '${COMMAND_NAME} cli'."
        ;;
    --uninstall)
        unlink_command
        unlink_man_pages
        ;;
    -h | --help) usage ;;
    *)
        usage >&2
        exit 1
        ;;
esac
