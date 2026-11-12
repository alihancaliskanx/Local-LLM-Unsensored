# shell/web.zsh — Tor Web Search (qwsearch) and CLL Web Gateway (cll)

_qwsearch_usage() {
  cat << 'EOF'
Usage: qwsearch [-r 0..4] [-n limit] [--raw] [--json] [--leak-test] [--new-circuit] <query>

Privacy-preserving, Tor-only web search synthesis for local Qwen3-4B.
Enforces strict Fail-Closed OPSEC: No packets leave outside Tor.

Options:
  -r <0..4>       Reasoning effort (0: off, 1: low, 2: medium [default], 3: high, 4: max)
  -n <limit>      Number of search results to retrieve (default: 5)
  --raw           Output raw Markdown search results without LLM synthesis
  --json          Output structured search results in JSON format
  --leak-test     Audit Tor circuit and verify exit IP via check.torproject.org
  --new-circuit   Request a new Tor identity (SIGNAL NEWNYM) before searching
  -h, --help      Show this help message
EOF
}

qwsearch() {
  local script_path="${QWEN_DIR}/cll/search.py"
  if [[ ! -f "$script_path" ]]; then
    echo "Error: Search module not found at ${script_path}" >&2
    return 1
  fi

  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    _qwsearch_usage
    return 0
  fi

  PYTHONPATH="${QWEN_DIR}" python3 -m cll.search "$@"
}

_cll_usage() {
  cat << 'EOF'
Usage: cll [--no-browser] [--port 41625] [stop]

Chat Local LLM (CLL) — Authentic llama-ui with LLM Power Bar,
Token Limit Select (up to 48K, 32K default), Zero-Log Privacy, and Tor Web / .onion Search.

Options:
  stop            Stops CLL server and background llama-server
  --no-browser    Starts server without automatically opening browser
  --port <port>   Port to bind CLL server (default: 41625)
  -h, --help      Show this help message
EOF
}

cll() {
  local script_path="${QWEN_DIR}/cll/server.py"
  local port="41625"
  local open_browser=1

  if [[ ! -f "$script_path" ]]; then
    echo "Error: CLL server module not found at ${script_path}" >&2
    return 1
  fi

  if [[ "${1:-}" == "stop" ]]; then
    echo "Stopping CLL server and llama-server..."
    pkill -f 'cll\.server|cll/server\.py|cll_server\.py' 2>/dev/null || true
    pkill -x 'llama-server' 2>/dev/null || true
    sleep 0.3
    pkill -9 -x 'llama-server' 2>/dev/null || true
    echo "CLL stopped."
    return 0
  fi

  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    _cll_usage
    return 0
  fi

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --no-browser) open_browser=0; shift ;;
      --port) port="${2:-41625}"; shift 2 ;;
      *) shift ;;
    esac
  done

  if ss -ltn | grep -q ":${port} "; then
    local url="http://127.0.0.1:${port}"
    echo "CLL is already running at ${url}"
    echo "Tip: Run 'cll stop' to terminate active instances."
    if [[ $open_browser -eq 1 ]]; then
      if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$url" >/dev/null 2>&1 &
      elif [[ -n "${BROWSER:-}" ]]; then
        "$BROWSER" "$url" >/dev/null 2>&1 &
      else
        python3 -m webbrowser "$url" >/dev/null 2>&1 &
      fi
    fi
    return 0
  fi

  local browser_args=()
  if [[ $open_browser -eq 0 ]]; then
    browser_args+=("--no-browser")
  fi

  # Run in foreground so Ctrl+C (KeyboardInterrupt) gracefully stops the server.
  # The user can suspend with Ctrl+Z and type 'bg' if background execution is desired.
  PYTHONPATH="${QWEN_DIR}" python3 -m cll.server --port "$port" "${browser_args[@]}"
}

alias qw='qwserver'
alias qwc='qwcli'
alias qws='qwcli -s -p'
alias qwsr='qwsearch'
alias qwfind='qwsearch'
alias qwweb='cll'
alias qww='cll'
