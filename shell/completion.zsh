# shell/completion.zsh — Autocompletion definitions for qw* commands in Zsh

_qw_common_context_args() {
  local -a contexts
  contexts=(
    '16:16k tokens (~12k words, fast, low VRAM)'
    '32:32k tokens (~24k words, default balanced)'
    '48:48k tokens (~36k words, max context)'
  )
  _describe -t contexts 'context size' contexts
}

_qw_common_reasoning_args() {
  local -a reasoning
  reasoning=(
    '0:Off (direct output, fastest)'
    '1:Low reasoning effort'
    '2:Medium reasoning effort (default)'
    '3:High reasoning effort (step-by-step)'
    '4:Maximum reasoning effort (deep analysis)'
  )
  _describe -t reasoning 'reasoning effort' reasoning
}

_qwfile_completion() {
  _arguments -s \
    '-c[Context tokens in thousands]:context:_qw_common_context_args' \
    '-r[Reasoning effort level (0..4)]:reasoning:_qw_common_reasoning_args' \
    '-f[File format override]:format:(pdf txt code)' \
    '--keep[Preserve modular notes in /tmp/local-llm/]' \
    '--export[Export final synthesis report to path]:export_file:_files' \
    '(-h --help)'{-h,--help}'[Show usage information]' \
    '1:target:_files' \
    '*:prompt:_default'
}

_qwsec_completion() {
  _arguments -s \
    '-c[Context tokens in thousands]:context:_qw_common_context_args' \
    '-r[Reasoning effort level (0..4)]:reasoning:_qw_common_reasoning_args' \
    '(-h --help)'{-h,--help}'[Show usage information]' \
    '1:target:_files' \
    '*:prompt:_default'
}

_qwpipe_completion() {
  _arguments -s \
    '-c[Context tokens in thousands]:context:_qw_common_context_args' \
    '-r[Reasoning effort level (0..4)]:reasoning:_qw_common_reasoning_args' \
    '(-h --help)'{-h,--help}'[Show usage information]' \
    '*:prompt:_default'
}

_qwcli_completion() {
  _arguments -s \
    '-c[Context tokens in thousands]:context:_qw_common_context_args' \
    '-r[Reasoning effort level (0..4)]:reasoning:_qw_common_reasoning_args' \
    '-s[Single-turn query mode]' \
    '-p[Initial prompt text]:prompt:_default' \
    '--rules[Enable system rules]' \
    '--no-rules[Disable system rules]' \
    '(-h --help)'{-h,--help}'[Show usage information]' \
    '*:prompt:_default'
}

_qwserver_completion() {
  _arguments -s \
    '-c[Context tokens in thousands]:context:_qw_common_context_args' \
    '-p[Server port (default 8080)]:port:_default' \
    '-r[Reasoning effort level (0..4)]:reasoning:_qw_common_reasoning_args' \
    '(-h --help)'{-h,--help}'[Show usage information]'
}

_qwsearch_completion() {
  _arguments -s \
    '-r[Reasoning effort level (0..4)]:reasoning:_qw_common_reasoning_args' \
    '-n[Result limit]:limit:(3 5 10)' \
    '--raw[Output raw markdown search results]' \
    '--json[Output structured JSON results]' \
    '--leak-test[Perform Tor circuit leak and IP check]' \
    '--new-circuit[Request fresh Tor circuit/IP]' \
    '(-h --help)'{-h,--help}'[Show usage information]' \
    '*:query:_default'
}

# Register completions if running in Zsh with compsys enabled
if [[ -n "${ZSH_VERSION:-}" ]] && (( $+functions[compdef] )); then
  compdef _qwfile_completion qwfile
  compdef _qwsec_completion qwsec
  compdef _qwpipe_completion qwpipe
  compdef _qwcli_completion qwcli
  compdef _qwcli_completion qws
  compdef _qwserver_completion qwserver
  compdef _qwsearch_completion qwsearch
fi
