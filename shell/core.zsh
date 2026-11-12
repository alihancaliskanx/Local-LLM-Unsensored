# shell/core.zsh — Shared state, context/reasoning resolvers, and process management

if [[ -z "${QWEN_DIR:-}" ]]; then
  if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
    QWEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  elif [[ -n "${ZSH_VERSION:-}" ]]; then
    QWEN_DIR="$(cd "$(dirname "${(%):-%x}")/.." && pwd)"
  else
    QWEN_DIR="$HOME/Local-LLM-Unsensored"
  fi
fi
export QWEN_DIR

MAX_MODEL_CTX=49152

# Helper: calculate context size with model limit enforcement (default: 32K, max: 48K)
_qw_resolve_ctx() {
  local val="${1:-32}"
  local res
  if [[ "$val" =~ ^[0-9]+$ ]]; then
    if (( val <= 256 )); then
      res=$(( val * 1024 ))
    else
      res="$val"
    fi
  else
    res=32768
  fi

  if (( res > MAX_MODEL_CTX )); then
    echo "Warning: Specified context (${res}) exceeds model limit of ${MAX_MODEL_CTX} ($(( MAX_MODEL_CTX / 1024 ))k). Capped at ${MAX_MODEL_CTX}." >&2
    res=$MAX_MODEL_CTX
  fi
  echo "$res"
}

# Helper: resolve reasoning level (0..4, default: 2 medium)
_qw_resolve_reasoning() {
  local r="${1:-2}"
  case "$r" in
    0|off|none)
      QW_R_LABEL="Off"
      QW_R_LEVEL="0"
      QW_R_FLAGS=(--reasoning off)
      ;;
    1|low)
      QW_R_LABEL="Low"
      QW_R_LEVEL="1"
      QW_R_FLAGS=(--reasoning on --reasoning-effort low)
      ;;
    3|high)
      QW_R_LABEL="High"
      QW_R_LEVEL="3"
      QW_R_FLAGS=(--reasoning on --reasoning-effort high)
      ;;
    4|max)
      QW_R_LABEL="Max"
      QW_R_LEVEL="4"
      QW_R_FLAGS=(--reasoning on --reasoning-effort max)
      ;;
    2|medium|*)
      QW_R_LABEL="Medium"
      QW_R_LEVEL="2"
      QW_R_FLAGS=(--reasoning on --reasoning-effort medium)
      ;;
  esac
}

# Stop running llama instances
qstop() {
  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: qstop"
    return 0
  fi
  pkill -x 'llama-server|llama-cli' 2>/dev/null && echo "Local LLM processes stopped." || echo "No active processes found."
}

# Helper: cleanly extract the last Assistant block from llama-cli -o file
_qw_extract_assistant() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  awk '
    /^Assistant:[[:space:]]*/ {
      found=1
      sub(/^Assistant:[[:space:]]*/, "")
      content = ($0 != "" ? $0 : "")
      next
    }
    found { content = (content == "" ? $0 : content "\n" $0) }
    END { if (found) print content }
  ' "$f"
}
