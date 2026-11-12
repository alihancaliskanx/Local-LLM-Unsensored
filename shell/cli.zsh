# shell/cli.zsh — Terminal LLM runners (qwserver, qwcli, qwfile, qwsec, qwpipe)

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
        echo "Error: Invalid option. Usage: qwserver [-c 16|32|48] [-r 0..4] [-p port]" >&2
        return 1
        ;;
    esac
  done
  shift $((OPTIND - 1))

  local ctx
  ctx="$(_qw_resolve_ctx "$ctx_arg")"
  _qw_resolve_reasoning "$r_arg"
  echo "── [Qwen3-4B Server | Port: ${port} | Max Tokens: ${ctx} ($(( ctx / 1024 ))k) | Reasoning: ${QW_R_LABEL} (${QW_R_LEVEL})] ──"
  CTX="${ctx}" PORT="${port}" "${QWEN_DIR}/qwen-local" server "${QW_R_FLAGS[@]}" "$@"
}

_qwcli_usage() {
  cat << 'EOF'
Usage: qwcli [-c 16|32|48] [-r 0..4] [-s] [-p "prompt"] [--rules|--no-rules] [extra flags...]

Options:
  -c <num>       Context tokens (16 -> 16384, 32 -> 32768 [default], 48 -> 49152 max)
  -r <0..4>      Reasoning effort (0: off, 1: low, 2: medium [default], 3: high, 4: max)
  -s             Single-turn mode (answers once and exits cleanly)
  -p <prompt>    Initial prompt text
  --rules        Enable system rules (prompts/cli_rules.md)
  --no-rules     Disable system rules for raw / uncensored generation
  -h, --help     Show this help
EOF
}

qwcli() {
  local ctx_arg="32" r_arg="2" single_turn=0 prompt="" rules_opt="auto"
  local OPTIND=1 opt
  while getopts ":c:r:sp:h-:" opt; do
    case "$opt" in
      c) ctx_arg="$OPTARG" ;;
      r) r_arg="$OPTARG" ;;
      s) single_turn=1 ;;
      p) prompt="$OPTARG" ;;
      h) _qwcli_usage; return 0 ;;
      -)
        case "$OPTARG" in
          rules) rules_opt="on" ;;
          no-rules) rules_opt="off" ;;
          help) _qwcli_usage; return 0 ;;
          *) echo "Error: Invalid option '--${OPTARG}'. Usage: qwcli --help" >&2; return 1 ;;
        esac
        ;;
      *) echo "Error: Invalid option. Usage: qwcli --help" >&2; return 1 ;;
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
  elif [[ "$single_turn" -eq 1 && -z "${RULES_PATH:-}" ]]; then
    rules_enabled=0
    rules_env=(RULES_PATH="/dev/null")
  fi

  local rules_label="On"
  [[ "$rules_enabled" -eq 0 ]] && rules_label="Off"

  echo "── [Qwen3-4B | Max Tokens: ${ctx} ($(( ctx / 1024 ))k) | Reasoning: ${QW_R_LABEL} (${QW_R_LEVEL}) | Rules: ${rules_label}] ──"

  if [[ "$single_turn" -eq 1 ]]; then
    local tmpfile prompt_file=""
    tmpfile="$(mktemp)"
    local p_args=()
    if [[ -n "$prompt" ]]; then
      prompt_file="$(mktemp)"
      printf '%s' "$prompt" > "$prompt_file"
      p_args=(-f "$prompt_file")
    fi
    env "${rules_env[@]}" CTX="${ctx}" "${QWEN_DIR}/qwen-local" cli --simple-io --log-disable -st "${p_args[@]}" "${QW_R_FLAGS[@]}" -o "${tmpfile}" "$@" >/dev/null
    _qw_extract_assistant "${tmpfile}"
    rm -f "${tmpfile}" ${prompt_file:+"$prompt_file"}
  else
    local p_args=()
    if [[ -n "$prompt" ]]; then
      p_args=(-p "$prompt")
    fi
    env "${rules_env[@]}" CTX="${ctx}" "${QWEN_DIR}/qwen-local" cli "${p_args[@]}" "${QW_R_FLAGS[@]}" "$@"
  fi
}

_qwfile_usage() {
  cat << 'EOF'
Usage: qwfile [-c 16|32|48] [-r 0..4] [-f pdf|txt|code] <file> [prompt]

Options:
  -c <num>     Context tokens (16 -> 16384, 32 -> 32768 [default], 48 -> 49152)
  -r <0..4>    Reasoning effort (0: off, 1: low, 2: medium [default], 3: high, 4: max)
  -f <format>  File format (pdf, txt, code). Auto-detected from extension if omitted.
  -h, --help   Show this help.
EOF
}

qwfile() {
  local ctx_arg="32" r_arg="2" format=""
  local OPTIND=1 opt
  while getopts ":c:r:f:h-:" opt; do
    case "$opt" in
      c) ctx_arg="$OPTARG" ;;
      r) r_arg="$OPTARG" ;;
      f) format="$OPTARG" ;;
      h) _qwfile_usage; return 0 ;;
      -)
        case "$OPTARG" in
          help) _qwfile_usage; return 0 ;;
          *) echo "Error: Invalid option '--${OPTARG}'. Usage: qwfile --help" >&2; return 1 ;;
        esac
        ;;
      *) echo "Error: Invalid option. Usage: qwfile --help" >&2; return 1 ;;
    esac
  done
  shift $((OPTIND - 1))

  local file="${1:-}"
  local prompt="${2:-Analyze this file, describe what it does and identify any issues:}"
  [[ $# -gt 0 ]] && shift
  [[ $# -gt 0 ]] && shift

  if [[ -z "$file" || ! -f "$file" ]]; then
    echo "Error: No valid file specified." >&2
    echo "Usage: qwfile [-c 16|32|48] [-r 0..4] [-f pdf|txt|code] <file> [prompt]" >&2
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

  local tmpfile prompt_file
  tmpfile="$(mktemp)"
  prompt_file="$(mktemp)"

  cat <<EOF > "${prompt_file}"
You are an expert software and document analysis assistant. Directly analyze the provided content and answer the user request with detailed, structured explanations. Do not generate unnecessary shell commands or irrelevant commit messages. Present your direct analysis.

Request: ${prompt}

Content to analyze (${file}):
\`\`\`
${content}
\`\`\`
EOF

  RULES_PATH=/dev/null CTX="${ctx}" "${QWEN_DIR}/qwen-local" cli --simple-io --log-disable -st -f "${prompt_file}" "${QW_R_FLAGS[@]}" -o "${tmpfile}" "$@" >/dev/null
  _qw_extract_assistant "${tmpfile}"
  rm -f "${tmpfile}" "${prompt_file}"
}

_qwsec_usage() {
  cat << 'EOF'
Usage: qwsec [-c 16|32|48] [-r 0..4] <file> [prompt]
       cat <file> | qwsec [-c 16|32|48] [-r 0..4] [prompt]

Security audit and vulnerability discovery (CWE/OWASP, memory safety, injection, crypto, logic bugs).
EOF
}

qwsec() {
  local ctx_arg="32" r_arg="2"
  local OPTIND=1 opt
  while getopts ":c:r:h-:" opt; do
    case "$opt" in
      c) ctx_arg="$OPTARG" ;;
      r) r_arg="$OPTARG" ;;
      h) _qwsec_usage; return 0 ;;
      -)
        case "$OPTARG" in
          help) _qwsec_usage; return 0 ;;
          *) echo "Error: Invalid option '--${OPTARG}'. Usage: qwsec --help" >&2; return 1 ;;
        esac
        ;;
      *) echo "Error: Invalid option. Usage: qwsec --help" >&2; return 1 ;;
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

  local tmpfile prompt_file
  tmpfile="$(mktemp)"
  prompt_file="$(mktemp)"

  cat <<EOF > "${prompt_file}"
Lütfen aşağıdaki kodu güvenlik açıkları (OWASP/CWE, memory safety, injection, yetkilendirme, broken crypto, mantık hataları) açısından ayrıntılı incele.
Her açık için ciddiyet seviyesini (Kritik, Yüksek, Orta, Düşük) ve sömürü mekanizmasını açıkla.
Ardından açıkları gideren eksiksiz, güvenli refactor edilmiş kodu ve doğrulamak için tek satırlık test komutunu sun:

Dosya: ${filename:-snippet}
\`\`\`
${code_content}
\`\`\`
EOF

  if [[ -n "$custom_prompt" ]]; then
    printf '\nEk Kullanıcı Talimatı: %s\n' "${custom_prompt}" >> "${prompt_file}"
  fi

  RULES_PATH="${QWEN_DIR}/prompts/cli_rules.md" CTX="${ctx}" "${QWEN_DIR}/qwen-local" cli --simple-io --log-disable -st -f "${prompt_file}" "${QW_R_FLAGS[@]}" -o "${tmpfile}" "$@" >/dev/null
  _qw_extract_assistant "${tmpfile}"
  rm -f "${tmpfile}" "${prompt_file}"
}

qwpipe() {
  local ctx_arg="32" r_arg="2"
  local OPTIND=1 opt
  while getopts ":c:r:h-:" opt; do
    case "$opt" in
      c) ctx_arg="$OPTARG" ;;
      r) r_arg="$OPTARG" ;;
      h) echo "Usage: <command> | qwpipe [-c 16|32|48] [-r 0..4] [prompt]"; return 0 ;;
      -)
        case "$OPTARG" in
          help) echo "Usage: <command> | qwpipe [-c 16|32|48] [-r 0..4] [prompt]"; return 0 ;;
          *) echo "Error: Invalid option '--${OPTARG}'. Usage: qwpipe --help" >&2; return 1 ;;
        esac
        ;;
      *) echo "Error: Invalid option. Usage: qwpipe --help" >&2; return 1 ;;
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

  local tmpfile prompt_file
  tmpfile="$(mktemp)"
  prompt_file="$(mktemp)"

  cat <<EOF > "${prompt_file}"
You are an expert system and text analysis assistant. Analyze the input data and answer the request directly with detailed explanations. Do not generate unnecessary shell commands or irrelevant commit messages.

Request: ${prompt}

Input:
\`\`\`
${input}
\`\`\`
EOF

  RULES_PATH=/dev/null CTX="${ctx}" "${QWEN_DIR}/qwen-local" cli --simple-io --log-disable -st -f "${prompt_file}" "${QW_R_FLAGS[@]}" -o "${tmpfile}" "$@" >/dev/null
  _qw_extract_assistant "${tmpfile}"
  rm -f "${tmpfile}" "${prompt_file}"
}
