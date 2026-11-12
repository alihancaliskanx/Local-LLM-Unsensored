#!/usr/bin/env python3
"""
cll.inference — Unified Terminal Inference and Document/Repo Analyzer for Qwen3-4B
Bridges terminal commands (qwfile, qwsec, qwpipe, qwcli) to:
1. Active llama-server HTTP API (streaming, 0s latency, no VRAM conflict)
2. Standalone qwen-local CLI fallback when llama-server is offline
"""

import sys
import os
import re
import json
import socket
import argparse
import subprocess
import urllib.request
import urllib.parse
from typing import Optional, Tuple, Dict, Any, List

def _find_repo_root() -> str:
    current = os.path.dirname(os.path.abspath(__file__))
    while current and current != "/":
        if os.path.isfile(os.path.join(current, "qwen-local")) and os.path.isfile(os.path.join(current, "cll", "server.py")):
            return current
        current = os.path.dirname(current)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REPO_ROOT = _find_repo_root()
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from cll.page_reader import fetch_page_text_tor, check_tor_active, resolve_repo_raw_url

TOR_PROXIES = {
    "http": "socks5h://127.0.0.1:9050",
    "https": "socks5h://127.0.0.1:9050"
}

REASONING_CONFIGS = {
    0: {"label": "Off", "flags": ["--reasoning", "off"], "level": "0"},
    1: {"label": "Low", "flags": ["--reasoning", "on", "--reasoning-effort", "low"], "level": "1"},
    2: {"label": "Medium", "flags": ["--reasoning", "on", "--reasoning-effort", "medium"], "level": "2"},
    3: {"label": "High", "flags": ["--reasoning", "on", "--reasoning-effort", "high"], "level": "3"},
    4: {"label": "Max", "flags": ["--reasoning", "on", "--reasoning-effort", "max"], "level": "4"},
}


def is_llama_server_running(host: str = "127.0.0.1", port: int = 8080) -> bool:
    """Checks whether llama-server is responsive on the OpenAI API port."""
    try:
        url = f"http://{host}:{port}/health"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def resolve_local_or_remote_target(target: str) -> Tuple[str, str, str]:
    """
    Resolves target into (content, resolved_label, format_type).
    Handles:
    - Existing local paths
    - Smart local workspace matching
    - Relative and tilde paths
    - GitHub URLs & raw files (over Tor)
    - GitHub owner/repo shorthand (over Tor)
    - General web URLs (over Tor)
    """
    target = target.strip()

    # 1. Check direct local file or directory
    expanded = os.path.expanduser(target)
    if os.path.isfile(expanded):
        return _read_local_file(expanded)
    if os.path.isdir(expanded):
        return "__DIRECTORY__", os.path.abspath(expanded), "dir"

    # 2. Smart local project resolution under common project roots
    home = os.path.expanduser("~")
    common_roots = [
        os.path.join(home, "Projects"),
        os.path.join(home, "Code"),
        os.path.join(home, "src"),
        os.path.join(home, "dev"),
        os.path.join(home, "workspace"),
        os.path.join(home, "Documents", "Code"),
    ]
    for root in common_roots:
        if not os.path.isdir(root):
            continue
        candidate = os.path.join(root, target.lstrip("/"))
        if os.path.isfile(candidate):
            return _read_local_file(candidate)
        if os.path.isdir(candidate):
            sys.stderr.write(f"[qwfile] Note: Resolved project directory to: {candidate}\n")
            return "__DIRECTORY__", os.path.abspath(candidate), "dir"

    # 3. Web URL (http:// or https://)
    if target.startswith("http://") or target.startswith("https://"):
        return _fetch_remote_url(target)

    # 4. GitHub shorthand: owner/repo or owner/repo/path/to/file
    gh_match = re.match(r"^([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)(?:/(.+))?$", target)
    if gh_match:
        owner = gh_match.group(1)
        repo = gh_match.group(2)
        subpath = gh_match.group(3)
        if subpath:
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/master/{subpath}"
            return _fetch_remote_url(raw_url, label=f"GitHub: {owner}/{repo}/{subpath}")
        else:
            repo_url = f"https://github.com/{owner}/{repo}"
            return _fetch_remote_url(repo_url, label=f"GitHub: {owner}/{repo}")

    raise FileNotFoundError(f"Target '{target}' is not a valid local file path or recognized remote URL.")


def _read_local_file(filepath: str) -> Tuple[str, str, str]:
    abs_path = os.path.abspath(filepath)
    ext = os.path.splitext(abs_path)[1].lower()

    if ext == ".pdf":
        try:
            res = subprocess.run(["pdftotext", abs_path, "-"], capture_output=True, text=True, check=True)
            return res.stdout, abs_path, "pdf"
        except Exception as e:
            sys.stderr.write(f"[qwfile warning] pdftotext extraction failed ({e}), attempting text read.\n")

    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
            return content, abs_path, ext.lstrip(".") or "txt"
    except Exception as e:
        raise IOError(f"Failed to read file {abs_path}: {e}")


def _fetch_remote_url(url: str, label: Optional[str] = None) -> Tuple[str, str, str]:
    if not check_tor_active():
        raise ConnectionError("Tor service (127.0.0.1:9050) is required for remote fetching but is offline.")

    # Convert GitHub web URLs to raw URLs where possible
    clean_url = url
    if "github.com/" in clean_url and "/blob/" in clean_url:
        clean_url = clean_url.replace("github.com/", "raw.githubusercontent.com/").replace("/blob/", "/")

    sys.stderr.write(f"[qwfile] Fetching remote content via Tor SOCKS5: {clean_url} ...\n")
    data = fetch_page_text_tor(clean_url, max_chars=32000)
    if not data or not data.get("text"):
        raise ConnectionError(f"Failed to fetch content from {clean_url} over Tor.")

    display_label = label or data.get("title") or clean_url
    return data["text"], display_label, "remote"


def stream_completion_from_server(
    messages: List[Dict[str, str]],
    temperature: float = 0.2,
    reasoning_level: int = 2,
    host: str = "127.0.0.1",
    port: int = 8080,
    capture_output: bool = False
) -> Tuple[bool, str]:
    """Streams token completion directly from llama-server HTTP API, optionally capturing text."""
    url = f"http://{host}:{port}/v1/chat/completions"
    payload: Dict[str, Any] = {
        "messages": messages,
        "temperature": temperature,
        "stream": True
    }
    effort_map = {0: "none", 1: "low", 2: "medium", 3: "high", 4: "max"}
    if reasoning_level > 0:
        payload["reasoning_effort"] = effort_map.get(reasoning_level, "medium")

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    accumulated = []
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            if resp.status != 200:
                return False, ""
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if line.startswith("data: "):
                    chunk_str = line[6:].strip()
                    if chunk_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(chunk_str)
                        delta_obj = chunk.get("choices", [{}])[0].get("delta", {})
                        delta = delta_obj.get("content", "")
                        reasoning_delta = delta_obj.get("reasoning_content", "")
                        if reasoning_delta:
                            if capture_output:
                                accumulated.append(reasoning_delta)
                            else:
                                sys.stdout.write(reasoning_delta)
                                sys.stdout.flush()
                        elif delta:
                            if capture_output:
                                accumulated.append(delta)
                            else:
                                sys.stdout.write(delta)
                                sys.stdout.flush()
                    except Exception:
                        pass
            if not capture_output:
                sys.stdout.write("\n")
                sys.stdout.flush()
            return True, "".join(accumulated)
    except Exception as e:
        sys.stderr.write(f"[llama-server stream error: {e}]\n")
        return False, ""


def run_qwen_cli_fallback(
    full_prompt: str,
    rules_path: Optional[str] = None,
    ctx: int = 32768,
    reasoning_level: int = 2,
    capture_output: bool = False
) -> Tuple[int, str]:
    """Runs standalone qwen-local CLI when llama-server is not running."""
    import tempfile
    r_flags = REASONING_CONFIGS.get(reasoning_level, REASONING_CONFIGS[2])["flags"]

    with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as pf:
        pf.write(full_prompt)
        prompt_file = pf.name
    with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tf:
        out_file = tf.name

    qwen_bin = os.path.join(REPO_ROOT, "qwen-local")
    if not os.path.exists(qwen_bin):
        qwen_bin = "qwen-local"

    cmd = [
        qwen_bin, "cli",
        "--simple-io", "--log-disable", "-st",
        "-c", str(ctx),
        "-f", prompt_file,
        "-o", out_file
    ] + r_flags

    env = os.environ.copy()
    if rules_path:
        env["RULES_PATH"] = rules_path
    else:
        env["RULES_PATH"] = "/dev/null"

    sys.stderr.write("[Qwen3-4B local CLI generating response...]\n")
    sys.stderr.flush()

    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        content = ""
        if os.path.exists(out_file):
            with open(out_file, "r", errors="ignore") as f:
                content = f.read()

        extracted = ""
        matches = re.split(r"(?m)^Assistant:[ \t]*", content)
        if len(matches) > 1:
            extracted = matches[-1].strip()
        elif content.strip():
            extracted = content.strip()

        if capture_output:
            return proc.returncode, extracted
        else:
            if extracted:
                sys.stdout.write(extracted + "\n")
                sys.stdout.flush()
            elif proc.stderr:
                sys.stderr.write(proc.stderr + "\n")
            return proc.returncode, extracted
    finally:
        for p in (prompt_file, out_file):
            if os.path.exists(p):
                os.remove(p)


def execute_inference(
    prompt: str,
    system_prompt: str = "",
    ctx: int = 32768,
    reasoning_level: int = 2,
    rules_path: Optional[str] = None,
    capture_output: bool = False
) -> Any:
    """Executes inference via active server first, with CLI fallback. If capture_output=True, returns string."""
    if is_llama_server_running():
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        success, text = stream_completion_from_server(
            messages,
            reasoning_level=reasoning_level,
            capture_output=capture_output
        )
        if success:
            return text if capture_output else 0

    # Fallback to local CLI
    full_prompt = prompt
    if system_prompt and not rules_path:
        full_prompt = f"{system_prompt}\n\n{prompt}"
    retcode, text = run_qwen_cli_fallback(
        full_prompt,
        rules_path=rules_path,
        ctx=ctx,
        reasoning_level=reasoning_level,
        capture_output=capture_output
    )
    return text if capture_output else retcode


def main():
    parser = argparse.ArgumentParser(description="cll.inference — Unified Qwen3-4B Terminal Engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. file subcommand (qwfile)
    p_file = subparsers.add_parser("file", help="Analyze file, code, or remote repository")
    p_file.add_argument("target", help="File path, GitHub repo (owner/repo), or URL")
    p_file.add_argument("prompt", nargs="*", default=[], help="Prompt or question")
    p_file.add_argument("-c", "--ctx", type=int, default=32768, help="Context tokens (default: 32768)")
    p_file.add_argument("-r", "--reasoning", type=int, default=2, choices=[0, 1, 2, 3, 4], help="Reasoning level (0..4, default: 2)")
    p_file.add_argument("-f", "--format", default="", help="File format override (e.g. pdf, txt, code)")
    p_file.add_argument("--keep", action="store_true", help="Preserve persistent copy of notes and report under ~/.local/share/local-llm/reports/")
    p_file.add_argument("--export", default=None, help="Custom export directory for reports and notes")

    # 2. sec subcommand (qwsec)
    p_sec = subparsers.add_parser("sec", help="Security audit and vulnerability analysis")
    p_sec.add_argument("target", nargs="?", default="", help="File path, code snippet, or omit for stdin")
    p_sec.add_argument("prompt", nargs="*", default=[], help="Extra user instructions")
    p_sec.add_argument("-c", "--ctx", type=int, default=32768, help="Context tokens (default: 32768)")
    p_sec.add_argument("-r", "--reasoning", type=int, default=2, choices=[0, 1, 2, 3, 4], help="Reasoning level")

    # 3. pipe subcommand (qwpipe)
    p_pipe = subparsers.add_parser("pipe", help="Analyze input streamed through stdin pipe")
    p_pipe.add_argument("prompt", nargs="*", default=[], help="Prompt or task")
    p_pipe.add_argument("-c", "--ctx", type=int, default=32768, help="Context tokens (default: 32768)")
    p_pipe.add_argument("-r", "--reasoning", type=int, default=2, choices=[0, 1, 2, 3, 4], help="Reasoning level")

    # 4. query subcommand (qwcli / qws)
    p_query = subparsers.add_parser("query", help="Direct single-turn query")
    p_query.add_argument("prompt", nargs="+", help="User prompt")
    p_query.add_argument("-c", "--ctx", type=int, default=32768, help="Context tokens (default: 32768)")
    p_query.add_argument("-r", "--reasoning", type=int, default=2, choices=[0, 1, 2, 3, 4], help="Reasoning level")
    p_query.add_argument("--rules", action="store_true", help="Enable system rules (prompts/cli_rules.md)")

    args = parser.parse_args()

    # Context resolution (allow 16, 32, 48 shorthand)
    ctx = args.ctx
    if ctx in (16, 32, 48):
        ctx = ctx * 1024
    if ctx > 49152:
        ctx = 49152

    reasoning_level = args.reasoning
    r_cfg = REASONING_CONFIGS.get(reasoning_level, REASONING_CONFIGS[2])

    if args.command == "file":
        try:
            content, label, fmt = resolve_local_or_remote_target(args.target)
        except Exception as e:
            sys.stderr.write(f"Error: {e}\n")
            sys.exit(1)

        prompt_text = " ".join(args.prompt) if args.prompt else "Analyze this file, describe what it does and identify any issues:"

        # If target is an entire directory, launch progressive chunked project analyzer
        if fmt == "dir" or os.path.isdir(label):
            try:
                from cll.project_analyzer import explore_and_analyze_project
            except ImportError:
                sandbox_pa = os.path.join(REPO_ROOT, "temp", "sandbox", "repo-chunk-analyzer")
                if sandbox_pa not in sys.path:
                    sys.path.insert(0, sandbox_pa)
                from project_analyzer import explore_and_analyze_project

            def chunk_inference_runner(p, system_prompt="", ctx=ctx, reasoning_level=reasoning_level, capture_output=True):
                return execute_inference(
                    p,
                    system_prompt=system_prompt,
                    ctx=ctx,
                    reasoning_level=reasoning_level,
                    capture_output=capture_output
                )

            explore_and_analyze_project(
                project_path=label,
                user_prompt=prompt_text,
                inference_fn=chunk_inference_runner,
                ctx=ctx,
                reasoning_level=reasoning_level,
                base_notes_dir="/tmp/local-llm",
                keep_archive=args.keep,
                export_dir=args.export
            )
            sys.exit(0)

        # Resolve dependency context from in-memory symbol cache
        dep_context = ""
        if os.path.isfile(label):
            try:
                from cll import symbol_resolver
                proj_root = REPO_ROOT
                cand_root = os.path.dirname(os.path.abspath(label))
                while cand_root and cand_root != "/":
                    if os.path.exists(os.path.join(cand_root, ".git")) or os.path.exists(os.path.join(cand_root, "CMakeLists.txt")):
                        proj_root = cand_root
                        break
                    cand_root = os.path.dirname(cand_root)

                sym_cache = symbol_resolver.SymbolCache()
                d_ctx, metrics = symbol_resolver.build_relevant_dependency_context(
                    target_content=content,
                    target_file_path=label,
                    project_root=proj_root,
                    cache=sym_cache
                )
                if metrics.get("symbols_injected", 0) > 0:
                    dep_context = d_ctx
                    sys.stderr.write(f"[qwfile] Injected {metrics['symbols_injected']} relevant dependency symbols from {metrics['dependencies_resolved']} headers.\n")
                    sys.stderr.flush()
                sym_cache.clear()
            except Exception:
                pass

        sys.stderr.write(f"── [Qwen3-4B | File: {label} | Max Tokens: {ctx} ({ctx // 1024}k) | Reasoning: {r_cfg['label']} ({r_cfg['level']})] ──\n")
        system_prompt = (
            "You are an expert software and document analysis assistant. "
            "Directly analyze the provided content and answer the user request with detailed, structured explanations. "
            "Do not generate unnecessary shell commands or irrelevant commit messages. Present your direct analysis."
        )
        full_user_prompt = (
            f"Request: {prompt_text}\n\n"
            f"{dep_context}"
            f"Content to analyze ({label}):\n"
            f"```\n{content}\n```"
        )
        code = execute_inference(full_user_prompt, system_prompt=system_prompt, ctx=ctx, reasoning_level=reasoning_level)
        sys.exit(code)

    elif args.command == "sec":
        code_content = ""
        filename = ""
        prompt_text = " ".join(args.prompt) if args.prompt else ""
        if args.target and (os.path.isfile(args.target) or os.path.isfile(os.path.expanduser(args.target))):
            filename = os.path.abspath(os.path.expanduser(args.target))
            with open(filename, "r", encoding="utf-8", errors="replace") as f:
                code_content = f.read()
        elif not sys.stdin.isatty():
            code_content = sys.stdin.read()
            if args.target and not prompt_text:
                prompt_text = args.target
        elif args.target:
            code_content = args.target
        else:
            sys.stderr.write("Error: No file or code provided for security audit.\nUsage: qwsec <file> or cat <file> | qwsec\n")
            sys.exit(1)

        label = filename or "code snippet"
        sys.stderr.write(f"── [Security Audit & Vulnerability Scan: {label} | Reasoning: {r_cfg['label']}] ──\n")

        rules_file = os.path.join(REPO_ROOT, "prompts", "cli_rules.md")
        system_prompt = (
            "You are an elite application security auditor and vulnerability researcher. "
            "Identify security vulnerabilities (OWASP/CWE, memory safety, injection, broken crypto, auth flaws, logic bugs). "
            "For each finding, explain the exploit mechanism, severity level, and provide safe refactored code."
        )
        user_prompt = (
            f"Lütfen aşağıdaki kodu güvenlik açıkları açısından ayrıntılı incele.\n\n"
            f"Hedef: {label}\n```\n{code_content}\n```\n"
        )
        if prompt_text:
            user_prompt += f"\nEk Talimat: {prompt_text}\n"

        code = execute_inference(user_prompt, system_prompt=system_prompt, ctx=ctx, reasoning_level=reasoning_level, rules_path=rules_file)
        sys.exit(code)

    elif args.command == "pipe":
        if sys.stdin.isatty():
            sys.stderr.write("Error: No input received from pipe.\nUsage: <command> | qwpipe [prompt]\n")
            sys.exit(1)
        input_data = sys.stdin.read()
        if not input_data.strip():
            sys.stderr.write("Error: Piped input is empty.\n")
            sys.exit(1)

        prompt_text = " ".join(args.prompt) if args.prompt else "Analyze and summarize the following output:"
        sys.stderr.write(f"── [Qwen3-4B | Max Tokens: {ctx} ({ctx // 1024}k) | Reasoning: {r_cfg['label']} ({r_cfg['level']})] ──\n")
        system_prompt = (
            "You are an expert system and text analysis assistant. "
            "Analyze the input data and answer the request directly with detailed explanations."
        )
        user_prompt = f"Request: {prompt_text}\n\nInput:\n```\n{input_data}\n```"
        code = execute_inference(user_prompt, system_prompt=system_prompt, ctx=ctx, reasoning_level=reasoning_level)
        sys.exit(code)

    elif args.command == "query":
        prompt_text = " ".join(args.prompt)
        rules_path = os.path.join(REPO_ROOT, "prompts", "cli_rules.md") if args.rules else None
        sys.stderr.write(f"── [Qwen3-4B | Max Tokens: {ctx} ({ctx // 1024}k) | Reasoning: {r_cfg['label']} ({r_cfg['level']})] ──\n")
        code = execute_inference(prompt_text, ctx=ctx, reasoning_level=reasoning_level, rules_path=rules_path)
        sys.exit(code)


if __name__ == "__main__":
    main()

