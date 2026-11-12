# qwen.zsh — Entry point for Qwen3-4B shell functions
# Sources modular shell components from shell/

if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
  QWEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
elif [[ -n "${ZSH_VERSION:-}" ]]; then
  QWEN_DIR="$(cd "$(dirname "${(%):-%x}")" && pwd)"
else
  QWEN_DIR="${QWEN_DIR:-$HOME/Local-LLM-Unsensored}"
fi
export QWEN_DIR

source "${QWEN_DIR}/shell/core.zsh"
source "${QWEN_DIR}/shell/cli.zsh"
source "${QWEN_DIR}/shell/web.zsh"
