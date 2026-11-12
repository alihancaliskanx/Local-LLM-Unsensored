# qwen.zsh — Configurable shell functions for Qwen LLM runner (qwen-local)
# Location: /home/sups/Local-LLM-Unsensored/qwen.zsh

MAX_MODEL_CTX=49152

# Helper: calculate context size with model limit enforcement
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
    /^Assistant:/ { found=1; content=""; next }
    found { content = (content == "" ? $0 : content "\n" $0) }
    END { if (found) print content }
  ' "$f"
}

# Server with configurable context, reasoning, and port
qwserver() {
  local ctx_arg="32" port="8080" r_arg="2"
  local OPTIND=1 opt
  while getopts ":c:p:r:h-:" opt; do
    case "$opt" in
      c) ctx_arg="$OPTARG" ;;
      p) port="$OPTARG" ;;
      r) r_arg="$OPTARG" ;;
      h)
        echo "Usage: qwserver [-c 16|32|48] [-r 0..4] [-p port] [extra flags...]"
        return 0
        ;;
      -)
        case "$OPTARG" in
          help)
            echo "Usage: qwserver [-c 16|32|48] [-r 0..4] [-p port] [extra flags...]"
            return 0
            ;;
          *)
            echo "Error: Invalid option '--${OPTARG}'. Usage: qwserver --help" >&2
            return 1
            ;;
        esac
        ;;
      *)
        echo "Error: Invalid option. Usage: qwserver --help" >&2
        return 1
        ;;
    esac
  done
  shift $((OPTIND - 1))

  local ctx
  ctx="$(_qw_resolve_ctx "$ctx_arg")"
  _qw_resolve_reasoning "$r_arg"

  echo "── [Qwen3-4B Server | Port: ${port} | Max Tokens: ${ctx} ($(( ctx / 1024 ))k) | Reasoning: ${QW_R_LABEL} (${QW_R_LEVEL})] ──"
  CTX="${ctx}" PORT="${port}" qwen-local server "${QW_R_FLAGS[@]}" "$@"
}

# CLI interactive or single-turn
qwcli() {
  local ctx_arg="32" r_arg="2" single_turn=0 prompt="" rules_opt=""
  local OPTIND=1 opt
  while getopts ":c:r:sp:hR-:" opt; do
    case "$opt" in
      c) ctx_arg="$OPTARG" ;;
      r) r_arg="$OPTARG" ;;
      s) single_turn=1 ;;
      p) prompt="$OPTARG" ;;
      R) rules_opt="off" ;;
      h)
        echo "Usage: qwcli [-c 16|32|48] [-r 0..4] [-s] [-p 'prompt'] [-R|--no-rules|--rules] [extra flags...]"
        return 0
        ;;
      -)
        case "$OPTARG" in
          help)
            echo "Usage: qwcli [-c 16|32|48] [-r 0..4] [-s] [-p 'prompt'] [-R|--no-rules|--rules] [extra flags...]"
            return 0
            ;;
          no-rules) rules_opt="off" ;;
          rules) rules_opt="on" ;;
          rules=*) rules_opt="${OPTARG#rules=}" ;;
          *)
            echo "Error: Invalid option '--${OPTARG}'. Usage: qwcli --help" >&2
            return 1
            ;;
        esac
        ;;
      *)
        echo "Error: Invalid option. Usage: qwcli --help" >&2
        return 1
        ;;
    esac
  done
  shift $((OPTIND - 1))

  local ctx
  ctx="$(_qw_resolve_ctx "$ctx_arg")"
  _qw_resolve_reasoning "$r_arg"

  local rules_enabled=1
  local rules_env=()
  if [[ "$rules_opt" == "off" || "$rules_opt" == "0" ]]; then
    rules_enabled=0
    rules_env=(RULES_PATH="/dev/null")
  elif [[ "$rules_opt" == "on" || "$rules_opt" == "1" ]]; then
    rules_enabled=1
  elif [[ "$single_turn" -eq 1 ]]; then
    # In single-turn mode, default is off unless explicitly enabled or set in environment
    if [[ -z "${RULES_PATH:-}" ]]; then
      rules_enabled=0
      rules_env=(RULES_PATH="/dev/null")
    fi
  fi

  local rules_label="On"
  [[ "$rules_enabled" -eq 0 ]] && rules_label="Off"

  echo "── [Qwen3-4B | Max Tokens: ${ctx} ($(( ctx / 1024 ))k) | Reasoning: ${QW_R_LABEL} (${QW_R_LEVEL}) | Rules: ${rules_label}] ──"

  if [[ "$single_turn" -eq 1 ]]; then
    local tmpfile
    tmpfile="$(mktemp)"
    local p_args=()
    if [[ -n "$prompt" ]]; then
      p_args=(-p "$prompt")
    fi
    env "${rules_env[@]}" CTX="${ctx}" qwen-local cli --simple-io --log-disable -st "${p_args[@]}" "${QW_R_FLAGS[@]}" -o "${tmpfile}" "$@" >/dev/null
    _qw_extract_assistant "${tmpfile}"
    rm -f "${tmpfile}"
  else
    local p_args=()
    if [[ -n "$prompt" ]]; then
      p_args=(-p "$prompt")
    fi
    env "${rules_env[@]}" CTX="${ctx}" qwen-local cli "${p_args[@]}" "${QW_R_FLAGS[@]}" "$@"
  fi
}

_qwfile_usage() {
  cat << 'EOF'
Usage: qwfile [-c 16|32|48] [-r 0..4] [-f pdf|txt|code] <file> [prompt]

Options:
  -c <num>     Context tokens (e.g., -c 16 -> 16384, -c 32 -> 32768, -c 48 -> 49152; default: 32)
  -r <0..4>    Reasoning effort (0: off, 1: low, 2: medium [default], 3: high, 4: max)
  -f <format>  File format (pdf, txt, code). Auto-detected from extension if omitted.
  -h, --help   Show this help.
EOF
}

# Analyze file / PDF
qwfile() {
  local ctx_arg="32" r_arg="2" format=""
  local OPTIND=1 opt
  while getopts ":c:r:f:h-:" opt; do
    case "$opt" in
      c) ctx_arg="$OPTARG" ;;
      r) r_arg="$OPTARG" ;;
      f) format="$OPTARG" ;;
      h)
        _qwfile_usage
        return 0
        ;;
      -)
        case "$OPTARG" in
          help)
            _qwfile_usage
            return 0
            ;;
          *)
            echo "Error: Invalid option '--${OPTARG}'. Usage: qwfile --help" >&2
            return 1
            ;;
        esac
        ;;
      *)
        echo "Error: Invalid option. Usage: qwfile --help" >&2
        return 1
        ;;
    esac
  done
  shift $((OPTIND - 1))

  local file="${1:-}"
  local prompt="${2:-Analyze this file, describe what it does and identify any issues:}"
  [[ $# -gt 0 ]] && shift
  [[ $# -gt 0 ]] && shift

  if [[ -z "$file" || ! -f "$file" ]]; then
    echo "Error: No valid file specified." >&2
    echo "Usage: qwfile [-c 16|32] [-r 0..4] [-f pdf|txt|code] <file> [prompt]" >&2
    return 1
  fi

  local ctx
  ctx="$(_qw_resolve_ctx "$ctx_arg")"
  _qw_resolve_reasoning "$r_arg"

  local is_pdf=0
  if [[ "$format" == "pdf" || ( -z "$format" && "$file" == *.pdf ) ]]; then
    is_pdf=1
  fi

  local content=""
  if [[ "$is_pdf" -eq 1 ]]; then
    if ! command -v pdftotext &>/dev/null; then
      echo "Error: 'pdftotext' (poppler package) is required to parse PDF files." >&2
      return 1
    fi
    content="$(pdftotext "$file" -)"
  else
    content="$(cat "$file")"
  fi

  if [[ -z "$content" ]]; then
    echo "Error: File content is empty or unreadable." >&2
    return 1
  fi

  echo "── [Qwen3-4B | File: ${file} | Max Tokens: ${ctx} ($(( ctx / 1024 ))k) | Reasoning: ${QW_R_LABEL} (${QW_R_LEVEL})] ──"

  local tmpfile
  tmpfile="$(mktemp)"

  local full_prompt="You are an expert software and document analysis assistant. Directly analyze the provided content and answer the user request with detailed, structured explanations. Do not generate unnecessary shell commands or irrelevant commit messages. Present your direct analysis.

Request: ${prompt}

Content to analyze (${file}):
\`\`\`
${content}
\`\`\`"

  # Disable restrictive terminal rules.md for document analysis, mute prompt echoing, extract assistant response
  RULES_PATH=/dev/null CTX="${ctx}" qwen-local cli --simple-io --log-disable -st -p "${full_prompt}" "${QW_R_FLAGS[@]}" -o "${tmpfile}" "$@" >/dev/null
  _qw_extract_assistant "${tmpfile}"
  rm -f "${tmpfile}"
}

_qwsec_usage() {
  cat << 'EOF'
Usage: qwsec [-c 16|32|48] [-r 0..4] <file> [prompt]
       cat <file> | qwsec [-c 16|32|48] [-r 0..4] [prompt]

Security audit and vulnerability discovery:
  Scans code for security vulnerabilities (CWE/OWASP, memory safety, injection, broken crypto,
  race conditions, logic bugs, OPSEC leaks) and provides secure refactored code and test commands.

Options:
  -c <num>     Context tokens (e.g. 16 -> 16384, 32 -> 32768, 48 -> 49152; default: 32)
  -r <0..4>    Reasoning effort (0: off, 1: low, 2: medium [default], 3: high, 4: max)
  -h, --help   Show this help.
EOF
}

# Dedicated CLI Code Security Audit & Vulnerability Discovery
qwsec() {
  local ctx_arg="32" r_arg="2"
  local OPTIND=1 opt
  while getopts ":c:r:h-:" opt; do
    case "$opt" in
      c) ctx_arg="$OPTARG" ;;
      r) r_arg="$OPTARG" ;;
      h)
        _qwsec_usage
        return 0
        ;;
      -)
        case "$OPTARG" in
          help)
            _qwsec_usage
            return 0
            ;;
          *)
            echo "Error: Invalid option '--${OPTARG}'. Usage: qwsec --help" >&2
            return 1
            ;;
        esac
        ;;
      *)
        echo "Error: Invalid option. Usage: qwsec --help" >&2
        return 1
        ;;
    esac
  done
  shift $((OPTIND - 1))

  local target="${1:-}"
  local custom_prompt="${2:-}"
  [[ $# -gt 0 ]] && shift
  [[ $# -gt 0 ]] && shift

  local code_content=""
  local filename=""
  if [[ -n "$target" && -f "$target" ]]; then
    filename="$target"
    code_content="$(cat "$target")"
  elif [[ ! -t 0 ]]; then
    code_content="$(cat)"
    if [[ -n "$target" && -z "$custom_prompt" ]]; then
      custom_prompt="$target"
    fi
  elif [[ -n "$target" ]]; then
    code_content="$target"
  else
    echo "Error: No file or code provided for security audit." >&2
    echo "Usage: qwsec <file> or cat <file> | qwsec" >&2
    return 1
  fi

  local ctx
  ctx="$(_qw_resolve_ctx "$ctx_arg")"
  _qw_resolve_reasoning "$r_arg"

  local label_target="${filename:-code snippet}"
  echo "── [Security Audit & Vulnerability Scan: ${label_target} | Reasoning: ${QW_R_LABEL}] ──"

  local audit_prompt="Lütfen aşağıdaki kodu güvenlik açıkları (OWASP/CWE, memory safety, injection, yetkilendirme, broken crypto, mantık hataları) açısından ayrıntılı incele.
Her açık için ciddiyet seviyesini (Kritik, Yüksek, Orta, Düşük) ve sömürü mekanizmasını açıkla.
Ardından açıkları gideren eksiksiz, güvenli refactor edilmiş kodu ve doğrulamak için tek satırlık test komutunu sun:

Dosya: ${filename:-snippet}
\`\`\`
${code_content}
\`\`\`"

  if [[ -n "$custom_prompt" ]]; then
    audit_prompt="${audit_prompt}

Ek Kullanıcı Talimatı: ${custom_prompt}"
  fi

  local tmpfile
  tmpfile="$(mktemp)"
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-${(%):-%x}}")" && pwd)"
  RULES_PATH="${script_dir}/cli_rules.md" CTX="${ctx}" qwen-local cli --simple-io --log-disable -st -p "${audit_prompt}" "${QW_R_FLAGS[@]}" -o "${tmpfile}" "$@" >/dev/null
  _qw_extract_assistant "${tmpfile}"
  rm -f "${tmpfile}"
}

# Pipe stdin into qwen-local
qwpipe() {
  local ctx_arg="32" r_arg="2"
  local OPTIND=1 opt
  while getopts ":c:r:h-:" opt; do
    case "$opt" in
      c) ctx_arg="$OPTARG" ;;
      r) r_arg="$OPTARG" ;;
      h)
        echo "Usage: <command> | qwpipe [-c 16|32|48] [-r 0..4] [prompt]"
        return 0
        ;;
      -)
        case "$OPTARG" in
          help)
            echo "Usage: <command> | qwpipe [-c 16|32|48] [-r 0..4] [prompt]"
            return 0
            ;;
          *)
            echo "Error: Invalid option '--${OPTARG}'. Usage: qwpipe --help" >&2
            return 1
            ;;
        esac
        ;;
      *)
        echo "Error: Invalid option. Usage: qwpipe --help" >&2
        return 1
        ;;
    esac
  done
  shift $((OPTIND - 1))

  local prompt="${1:-Analyze and summarize the following output:}"
  [[ $# -gt 0 ]] && shift
  local input
  input="$(cat)"

  if [[ -z "$input" ]]; then
    echo "Error: No input received from pipe." >&2
    return 1
  fi

  local ctx
  ctx="$(_qw_resolve_ctx "$ctx_arg")"
  _qw_resolve_reasoning "$r_arg"

  echo "── [Qwen3-4B | Max Tokens: ${ctx} ($(( ctx / 1024 ))k) | Reasoning: ${QW_R_LABEL} (${QW_R_LEVEL})] ──"

  local tmpfile
  tmpfile="$(mktemp)"

  local full_prompt="You are an expert system and text analysis assistant. Analyze the input data and answer the request directly with detailed explanations. Do not generate unnecessary shell commands or irrelevant commit messages.

Request: ${prompt}

Input:
\`\`\`
${input}
\`\`\`"

  RULES_PATH=/dev/null CTX="${ctx}" qwen-local cli --simple-io --log-disable -st -p "${full_prompt}" "${QW_R_FLAGS[@]}" -o "${tmpfile}" "$@" >/dev/null
  _qw_extract_assistant "${tmpfile}"
  rm -f "${tmpfile}"
}

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

Examples:
  qwsearch "Arch Linux latest news"
  qwsearch -r 3 "Explain recent Linux kernel scheduler changes"
  qwsearch --raw "systemd vulnerabilities" | qwpipe "summarize security impact"
  qwsearch --leak-test
  qwsearch --new-circuit "privacy tools"
EOF
}

# Tor-only web search with local Qwen synthesis
qwsearch() {
  local script_path="${QWEN_DIR:-/home/sups/Local-LLM-Unsensored}/qwsearch.py"
  if [[ ! -f "$script_path" ]]; then
    echo "Error: Search script not found at ${script_path}" >&2
    return 1
  fi

  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    _qwsearch_usage
    return 0
  fi

  python3 "$script_path" "$@"
}

_qwweb_usage() {
  cat << 'EOF'
Usage: qwweb [-p port] [--llama-url url]

Launches the local web agent UI with Tor-isolated browsing,
auto-detect search routing, and prompt injection shield.

Options:
  --port <port>       Port to bind the web agent server (default: 8088)
  --llama-url <url>   llama-server API endpoint (default: http://127.0.0.1:8080)
  -h, --help          Show this help message
EOF
}

# Tor-isolated Web Agent UI with Prompt Injection Shield
qwweb() {
  local script_path="${QWEN_DIR:-/home/sups/Local-LLM-Unsensored}/qwen-web.py"
  if [[ ! -f "$script_path" ]]; then
    echo "Error: Web agent script not found at ${script_path}" >&2
    return 1
  fi

  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    _qwweb_usage
    return 0
  fi

  python3 "$script_path" "$@"
}

# Backward compatible short aliases
alias qw='qwserver'
alias qwc='qwcli'
alias qws='qwcli -s -p'
alias qwsr='qwsearch'
alias qwfind='qwsearch'
alias qww='qwweb'

_cll_usage() {
  cat << 'EOF'
Usage: cll [--no-browser] [--port 41625] [stop]

Chat Local LLM (CLL) — Authentic llama-ui with LLM Power Bar,
Token Limit Select, Zero-Log Privacy, and Tor Web / .onion Search.

Options:
  stop            Stops CLL server and background llama-server
  --no-browser    Starts server without automatically opening browser
  --port <port>   Port to bind CLL server (default: 41625)
  -h, --help      Show this help message
EOF
}

# Chat Local LLM (CLL) Gateway
cll() {
  local script_path="${QWEN_DIR:-/home/sups/Local-LLM-Unsensored}/cll_server.py"
  local port="41625"
  local open_browser=1

  if [[ ! -f "$script_path" ]]; then
    echo "Error: CLL server script not found at ${script_path}" >&2
    return 1
  fi

  if [[ "${1:-}" == "stop" ]]; then
    echo "Stopping CLL server and llama-server..."
    pkill -f 'cll_server.py' 2>/dev/null || true
    pkill -x 'llama-server' 2>/dev/null || true
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
      --port) port="$2"; shift 2 ;;
      *) shift ;;
    esac
  done

  # Check if cll_server is already running on specified port
  if ! ss -ltn | grep -q ":${port} "; then
    echo "Starting CLL server on port ${port}..."
    python3 "$script_path" --port "$port" >/dev/null 2>&1 &
    local ready=0
    for i in {1..30}; do
      if ss -ltn | grep -q ":${port} "; then
        ready=1
        break
      fi
      sleep 0.2
    done
    if [[ $ready -eq 0 ]]; then
      echo "Error: CLL server failed to start on port ${port}" >&2
      return 1
    fi
  fi

  local url="http://127.0.0.1:${port}"
  echo "CLL running at ${url}"

  if [[ $open_browser -eq 1 ]]; then
    if command -v xdg-open >/dev/null 2>&1; then
      xdg-open "$url" >/dev/null 2>&1 &
    elif [[ -n "${BROWSER:-}" ]]; then
      "$BROWSER" "$url" >/dev/null 2>&1 &
    else
      python3 -m webbrowser "$url" >/dev/null 2>&1 &
    fi
  fi
}
