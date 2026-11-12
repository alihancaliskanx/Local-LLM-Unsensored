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

  if [[ "$single_turn" -eq 1 ]]; then
    local p_text="$prompt"
    [[ -z "$p_text" && $# -gt 0 ]] && p_text="$*"
    local rules_flag=()
    [[ "$rules_opt" == "on" || "$rules_opt" == "1" ]] && rules_flag=(--rules)
    PYTHONPATH="${QWEN_DIR}" python3 -m cll.inference query -c "$ctx_arg" -r "$r_arg" "${rules_flag[@]}" "$p_text"
    return $?
  fi

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
  fi

  local rules_label="On"
  [[ "$rules_enabled" -eq 0 ]] && rules_label="Off"

  echo "── [Qwen3-4B | Max Tokens: ${ctx} ($(( ctx / 1024 ))k) | Reasoning: ${QW_R_LABEL} (${QW_R_LEVEL}) | Rules: ${rules_label}] ──"

  local p_args=()
  if [[ -n "$prompt" ]]; then
    p_args=(-p "$prompt")
  fi
  env "${rules_env[@]}" CTX="${ctx}" "${QWEN_DIR}/qwen-local" cli "${p_args[@]}" "${QW_R_FLAGS[@]}" "$@"
}

_qwfile_usage() {
  cat << 'EOF'
Usage: qwfile [-c 16|32|48] [-r 0..4] [-f pdf|txt|code] <file_or_url_or_repo> [prompt]

Smart file, codebase, and remote repository analysis using local Qwen3-4B.
Supports local files, fuzzy project paths, remote URLs, and GitHub repos (over Tor).

Options:
  -c <num>     Context tokens (16 -> 16384, 32 -> 32768 [default], 48 -> 49152)
  -r <0..4>    Reasoning effort (0: off, 1: low, 2: medium [default], 3: high, 4: max)
  -f <format>  File format override (pdf, txt, code).
  -h, --help   Show this help.
EOF
}

qwfile() {
  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    _qwfile_usage
    return 0
  fi
  PYTHONPATH="${QWEN_DIR}" python3 -m cll.inference file "$@"
}

_qwsec_usage() {
  cat << 'EOF'
Usage: qwsec [-c 16|32|48] [-r 0..4] <file_or_code> [prompt]
       cat <file> | qwsec [-c 16|32|48] [-r 0..4] [prompt]

Security audit and vulnerability discovery (CWE/OWASP, memory safety, injection, crypto, logic bugs).
EOF
}

qwsec() {
  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    _qwsec_usage
    return 0
  fi
  PYTHONPATH="${QWEN_DIR}" python3 -m cll.inference sec "$@"
}

qwpipe() {
  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: <command> | qwpipe [-c 16|32|48] [-r 0..4] [prompt]"
    return 0
  fi
  PYTHONPATH="${QWEN_DIR}" python3 -m cll.inference pipe "$@"
}
