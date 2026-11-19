#!/usr/bin/env python3
"""
cll.opencode_bridge — Lightweight OpenAI-Compatible Agent Gateway for OpenCode + Local Qwen3-4B.
Prunes cloud system-prompt bloat, injects native autonomous Tor web search (`tor_search`),
translates `tor_search` / `websearch` into OpenCode `shell` (`torsearch`) calls, and recovers
raw JSON tool calls emitted without `<tool_call>` XML tags.
"""

import os
import re
import sys
import json
import time
import shlex
import socket
import argparse
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Any, List, Optional, Tuple, Set

import requests

LLAMA_BASE_URL = os.environ.get("LLAMA_SERVER_URL", "http://127.0.0.1:61232")
BRIDGE_HOST = os.environ.get("OPENCODE_BRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.environ.get("OPENCODE_BRIDGE_PORT", "61231"))

BLOCKED_TOOLS = {
    "experimental_image_generate",
    "execute",
    "skill",
    "webfetch",
    "websearch",
}

TOR_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "tor_search",
        "description": (
            "Search the live internet, GitHub, Wikipedia, ArXiv, and .onion dark web "
            "anonymously over Tor SOCKS5h with commercial/darkweb spam filtering and "
            "prompt-injection sanitization. Call this autonomously whenever you need "
            "current information, external facts, documentation, package versions, or CVEs "
            "at the start of a request OR in the middle of working on a multi-step task."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query keywords"
                },
                "deep": {
                    "type": "boolean",
                    "description": "Set true to also scrape and read full text of top result pages over Tor (default: false)"
                }
            },
            "required": ["query"],
            "additionalProperties": False
        },
        "strict": False
    }
}

DEFAULT_MAX_TOOL_RESULT_CHARS = 10000


def get_max_tool_chars() -> int:
    """Returns the configured tool output truncation limit from environment or default."""
    try:
        return int(os.environ.get("CLL_BRIDGE_MAX_OUTPUT", DEFAULT_MAX_TOOL_RESULT_CHARS))
    except (ValueError, TypeError):
        return DEFAULT_MAX_TOOL_RESULT_CHARS


MAX_TOOL_RESULT_CHARS = get_max_tool_chars()

AUTONOMOUS_TOR_DIRECTIVE = (
    "\n\n# Autonomous Tor Web Search & Senior Engineer Execution\n"
    "1. NO DEFINITIONS OR ELEMENTARY EXPLANATIONS: The user is a senior systems architect and reverse engineer who already knows all underlying concepts, protocols, security terminology, and programming concepts thoroughly. NEVER define or explain terms, protocols, libraries, or architectures (e.g. CAN bus, eBPF, zero-click, memory layout, AST, etc.) unless the user explicitly asks: 'What is X?'.\n"
    "2. NO INTRODUCTORY ESSAYS OR TUTORIALS: Omit background history, introductory overviews, conceptual tutorials, and unsolicited educational context.\n"
    "3. ZERO CHATTY FILLER & STORIES: Omit conversational preamble ('Sure! I can help with that', 'Here is the code:', 'In this implementation...'), storytelling, or narration. Immediately output the exact code, command, diff, or tool call.\n"
    "4. CONCISE & DENSE: Keep explanations strictly minimal. If a note is necessary for a non-obvious engineering choice, limit it to at most 1-2 dense technical bullet points.\n"
    "5. AUTONOMOUS TOR WEB SEARCH: You have direct access to the live internet, GitHub, ArXiv, and .onion dark web via `tor_search` (routed 100% over Tor SOCKS5h with spam & injection protection). Autonomously call `tor_search` whenever external documentation, exact API signatures, package versions, or CVE details are needed — both at the start of a request AND mid-task while reading/editing files.\n"
    "6. TOOL CALL FORMAT: When calling a tool, emit a valid tool call with {\"name\": \"<tool_name>\", \"arguments\": {...}} or wrapped in <tool_call></tool_call>.\n"
    "7. MANDATORY FILE CREATION & EDITING VIA TOOLS: When tools are available and you are asked to create or edit project files on disk, you MUST invoke the appropriate tool (such as `write`, `edit`, or `shell`) rather than merely displaying code in conversation. If answering general coding queries without a file write request, output the code block directly.\n"
    "8. DIRECT TOOL CALL: Do not announce, narrate, or describe the tool call before calling it. Execute the tool call directly.\n"
    "9. NO REPETITION / GROUNDED PATHS: Never invent or assume non-existent directory trees (e.g. `src/`, `model/`, `.ts` files). Always inspect actual directories via `list` or file tree first. Never repeat the same failed `glob` or `grep` pattern. If a search pattern yields 'No files found', adapt immediately instead of retrying the same pattern."
)


def prune_system_prompt(content: str) -> str:
    """Strips OpenCode Code Mode VM catalog and unused desktop/cloud skills bloat."""
    if not content:
        return content
    # Remove # Code Mode ... up to Today's date: (or end of <available_skills>)
    cleaned = re.sub(
        r"# Code Mode\b.*?(?=Today's date:|\Z)",
        "",
        content,
        flags=re.DOTALL
    )
    cleaned = re.sub(
        r"<available_skills>.*?</available_skills>\s*",
        "",
        cleaned,
        flags=re.DOTALL
    )
    cleaned = re.sub(
        r"When you create a worktree outside the current working directory.*?\n?",
        "",
        cleaned,
        flags=re.DOTALL
    )
    if "Autonomous Tor Web Search" not in cleaned:
        cleaned = cleaned.rstrip() + AUTONOMOUS_TOR_DIRECTIVE
    return cleaned


def _truncate_text(text: str, limit: int) -> str:
    """Helper to truncate text at a newline boundary with actionable guidance."""
    if "\x00" in text:
        orig = len(text)
        return f"[Binary file content omitted ({orig} bytes). File is present on disk.]"
    orig = len(text)
    if orig <= limit:
        return text

    lookback = min(1000, limit // 5)
    last_nl = text.rfind("\n", max(0, limit - lookback), limit)
    cut_idx = (last_nl + 1) if last_nl != -1 else limit

    warning = (
        f"\n\n[Bridge Warning: Output truncated from {orig} to {cut_idx} chars to prevent context overflow. "
        f"To inspect the remainder without context overflow, read specific line/byte ranges or narrow the query.]"
    )
    return text[:cut_idx] + warning


def truncate_large_content(content: Any, max_chars: Optional[int] = None) -> Any:
    """Truncates oversized tool outputs or messages to prevent context exhaustion and loops.

    Preserves line boundaries when possible and advises the model on offset/range reading.
    """
    limit = max_chars if max_chars is not None else get_max_tool_chars()
    if isinstance(content, str):
        return _truncate_text(content, limit)
    elif isinstance(content, list):
        truncated_list = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                part = dict(part)
                part["text"] = _truncate_text(part["text"], limit)
            truncated_list.append(part)
        return truncated_list
    return content


def transform_request_payload(data: Dict[str, Any]) -> Tuple[Dict[str, Any], Set[str]]:
    """Prunes prompt bloat, optimizes tool definitions, truncates oversized outputs, and injects `tor_search`."""
    tools = data.get("tools")
    valid_tool_names = set()

    if isinstance(tools, list) and len(tools) > 0:
        filtered_tools = []
        for t in tools:
            fn = t.get("function", {}) if isinstance(t, dict) else {}
            name = fn.get("name", "")
            if name and name not in BLOCKED_TOOLS:
                filtered_tools.append(t)
                valid_tool_names.add(name)

        filtered_tools.append(TOR_SEARCH_TOOL)
        valid_tool_names.add("tor_search")
        valid_tool_names.add("websearch")
        data["tools"] = filtered_tools

    # Sanitize and truncate messages
    messages = data.get("messages", [])
    if isinstance(messages, list):
        for m in messages:
            if not isinstance(m, dict):
                continue
            role = m.get("role")
            if role == "system" and isinstance(m.get("content"), str):
                m["content"] = prune_system_prompt(m["content"])
            elif role in ("tool", "user", "assistant"):
                m["content"] = truncate_large_content(m.get("content"))

    # Map reasoning_effort if present
    effort = data.pop("reasoning_effort", None)
    if effort in ("low", "medium", "high"):
        if effort == "low":
            data["temperature"] = 0.2
        elif effort == "medium":
            data["temperature"] = 0.4
        elif effort == "high":
            data["temperature"] = 0.6

    return data, valid_tool_names


def build_torsearch_shell_command(args_obj: Dict[str, Any]) -> str:
    """Converts `tor_search` arguments into a safe `torsearch` CLI command string."""
    query = str(args_obj.get("query", "")).strip()
    deep = bool(args_obj.get("deep", False))
    limit = int(args_obj.get("limit", 4))
    flags = f"-n {limit}"
    if deep:
        flags += " --deep"
    return f"torsearch {flags} {shlex.quote(query)}"


def rewrite_tool_call_entry(tc: Dict[str, Any]) -> Dict[str, Any]:
    """Rewrites `tor_search` or `websearch` tool call into OpenCode's native `shell` tool call."""
    fn = tc.get("function", {})
    name = fn.get("name", "")
    raw_args = fn.get("arguments", "{}")
    if name in ("tor_search", "websearch"):
        try:
            args_obj = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except Exception:
            args_obj = {"query": str(raw_args)}
        cmd = build_torsearch_shell_command(args_obj)
        fn["name"] = "shell"
        fn["arguments"] = json.dumps({"command": cmd}, ensure_ascii=False)
        tc["function"] = fn
    return tc


def try_parse_raw_json_tool_call(text: str, valid_tool_names: set) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Detects if the model emitted a tool call as JSON (either inside markdown code fences or raw).
    Returns (preceding_text, tool_call_dict) if found and name is in valid_tool_names.
    """
    if not text or not any(k in text for k in ('"name"', '"tool"', '"function"', '"function-name"')):
        return None

    cleaned_text = text.strip()
    prefix = ""
    json_candidate = None

    # Check for markdown code fences first
    fence_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*(?:```|$)', cleaned_text)
    if fence_match:
        json_candidate = fence_match.group(1).strip()
        prefix = cleaned_text[:fence_match.start()].strip()
        if prefix in ("```json", "```"):
            prefix = ""
    else:
        # Match standalone JSON object
        match = re.search(r'(\{[\s\S]*"(?:name|tool|function|function-name)"\s*:\s*"([a-zA-Z0-9_ -]+)"[\s\S]*\})\s*$', cleaned_text)
        if match:
            json_candidate = match.group(1).strip()
            prefix = cleaned_text[:match.start()].strip()

    if not json_candidate:
        return None

    try:
        parsed = json.loads(json_candidate)
        if isinstance(parsed, dict):
            raw_name = parsed.get("name") or parsed.get("tool") or parsed.get("function") or parsed.get("function-name")
            tool_name = str(raw_name).strip() if raw_name else ""
            if tool_name in valid_tool_names:
                args = parsed.get("arguments") or parsed.get("parameters") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                elif isinstance(args, list):
                    if tool_name in ("read", "read_file", "view"):
                        args = {"path": args[0]} if args else {}
                    elif tool_name in ("glob", "find"):
                        args = {"pattern": args[0]} if args else {}
                    elif tool_name in ("shell", "bash", "execute"):
                        args = {"command": args[0]} if args else {}
                    else:
                        args = {"args": args}
                elif not isinstance(args, dict):
                    args = {}
                tc = {
                    "index": 0,
                    "id": f"call_{int(time.time() * 1000)}",
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(args, ensure_ascii=False)
                    }
                }
                return prefix, rewrite_tool_call_entry(tc)
    except Exception:
        pass
    return None


def forward_request_with_retry(
    method: str,
    url: str,
    max_retries: int = 15,
    delay: float = 0.5,
    on_wait: Optional[Any] = None,
    **kwargs
) -> requests.Response:
    """Retries HTTP request if downstream LLAMA server is still initializing its socket."""
    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            resp = requests.request(method, url, **kwargs)
            if resp.status_code == 503 and b"Loading model" in resp.content:
                if attempt < max_retries - 1:
                    if on_wait:
                        try:
                            on_wait()
                        except Exception:
                            pass
                    time.sleep(delay)
                    continue
            return resp
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_err = e
            if attempt < max_retries - 1:
                if on_wait:
                    try:
                        on_wait()
                    except Exception:
                        pass
                time.sleep(delay)
            else:
                raise last_err
    if last_err:
        raise last_err
    raise RuntimeError("Unexpected retry failure")


class OpenCodeBridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        target_url = f"{LLAMA_BASE_URL}{self.path}"
        try:
            resp = forward_request_with_retry("GET", target_url, max_retries=15, delay=0.5, timeout=10)
            self.send_response(resp.status_code)
            self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(resp.content)))
            self.end_headers()
            self.wfile.write(resp.content)
        except Exception as e:
            err = json.dumps({"error": str(e)}).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length > 0 else b"{}"

        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception:
            data = {}

        is_stream = bool(data.get("stream", False))
        has_tools = bool(data.get("tools"))
        data, valid_tool_names = transform_request_payload(data)

        target_url = f"{LLAMA_BASE_URL}{self.path}"

        if not is_stream:
            try:
                resp = forward_request_with_retry("POST", target_url, max_retries=20, delay=0.5, json=data, timeout=300)
                resp_data = resp.json()
                if has_tools:
                    choices = resp_data.get("choices", [])
                    if choices:
                        msg = choices[0].get("message", {})
                        tcs = msg.get("tool_calls")
                        if tcs:
                            msg["tool_calls"] = [rewrite_tool_call_entry(tc) for tc in tcs]
                        else:
                            content = msg.get("content") or ""
                            parsed_tc = try_parse_raw_json_tool_call(content, valid_tool_names)
                            if parsed_tc:
                                prefix, tc_obj = parsed_tc
                                msg["content"] = prefix if prefix else None
                                msg["tool_calls"] = [tc_obj]
                                choices[0]["finish_reason"] = "tool_calls"
                out = json.dumps(resp_data, ensure_ascii=False).encode("utf-8")
                self.send_response(resp.status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
            except Exception as e:
                err = json.dumps({"error": {"message": str(e)}}).encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
            return

        # Streaming SSE handling
        try:
            resp = forward_request_with_retry("POST", target_url, max_retries=20, delay=0.5, json=data, stream=True, timeout=(10, 600))
        except Exception as e:
            err = json.dumps({"error": {"message": str(e)}}).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        send_lock = threading.Lock()

        def send_raw(b: bytes) -> None:
            with send_lock:
                try:
                    self.wfile.write(b)
                    self.wfile.flush()
                except Exception:
                    pass

        def send_sse(obj: Any) -> None:
            if isinstance(obj, str):
                line = f"data: {obj}\n\n"
            else:
                line = f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"
            send_raw(line.encode("utf-8"))

        stop_heartbeat = threading.Event()

        def heartbeat_worker():
            while not stop_heartbeat.wait(5.0):
                send_raw(b": ping\n\n")

        hb_thread = threading.Thread(target=heartbeat_worker, daemon=True)
        hb_thread.start()

        try:
            if not has_tools:
                for raw_line in resp.iter_lines(chunk_size=None, decode_unicode=False):
                    if raw_line:
                        send_raw(raw_line + b"\n\n")
                return

            accumulated_tcs: Dict[int, Dict[str, Any]] = {}
            tool_call_buffer: List[str] = []
            buffering_tool_call = False
            initial_check_buffer: List[str] = []
            is_checking_initial_json = False
            has_streamed_content = False
            sent_role = False
            usage_chunk = None
            meta_template: Dict[str, Any] = {
                "id": f"chatcmpl-{int(time.time() * 1000)}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": data.get("model", "qwen3-4b")
            }

            for line_str in resp.iter_lines(chunk_size=None, decode_unicode=True):
                if not line_str or not line_str.startswith("data: "):
                    continue
                payload_str = line_str[6:].strip()
                if payload_str == "[DONE]":
                    break

                try:
                    chunk = json.loads(payload_str)
                except Exception:
                    continue

                for k in ("id", "created", "model", "system_fingerprint"):
                    if k in chunk:
                        meta_template[k] = chunk[k]

                if chunk.get("usage"):
                    usage_chunk = chunk

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                choice = choices[0]
                delta = choice.get("delta", {})

                if delta.get("role") and not sent_role:
                    sent_role = True
                    send_sse({
                        **meta_template,
                        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]
                    })

                if "tool_calls" in delta and delta["tool_calls"]:
                    for tc_delta in delta["tool_calls"]:
                        idx = tc_delta.get("index", 0)
                        if idx not in accumulated_tcs:
                            accumulated_tcs[idx] = {
                                "index": idx,
                                "id": tc_delta.get("id") or f"call_{int(time.time() * 1000)}_{idx}",
                                "type": "function",
                                "function": {"name": "", "arguments": ""}
                            }
                        if tc_delta.get("id"):
                            accumulated_tcs[idx]["id"] = tc_delta["id"]
                        fn_delta = tc_delta.get("function", {})
                        if fn_delta.get("name"):
                            accumulated_tcs[idx]["function"]["name"] += fn_delta["name"]
                        if fn_delta.get("arguments"):
                            accumulated_tcs[idx]["function"]["arguments"] += fn_delta["arguments"]

                content_piece = delta.get("content")
                if content_piece:
                    if buffering_tool_call:
                        tool_call_buffer.append(content_piece)
                    elif "<tool_call>" in content_piece:
                        buffering_tool_call = True
                        if is_checking_initial_json:
                            tool_call_buffer = list(initial_check_buffer)
                            initial_check_buffer = []
                            is_checking_initial_json = False
                        parts = content_piece.split("<tool_call>", 1)
                        prefix = parts[0]
                        suffix = "<tool_call>" + parts[1]
                        if prefix:
                            has_streamed_content = True
                            send_sse({
                                **meta_template,
                                "choices": [{"index": 0, "delta": {"content": prefix}, "finish_reason": None}]
                            })
                        tool_call_buffer.append(suffix)
                    elif not has_streamed_content and not is_checking_initial_json:
                        stripped = content_piece.lstrip()
                        if not stripped:
                            # Leading whitespace, buffer temporarily
                            is_checking_initial_json = True
                            initial_check_buffer.append(content_piece)
                        elif stripped.startswith("{") or stripped.startswith("```"):
                            is_checking_initial_json = True
                            initial_check_buffer.append(content_piece)
                        else:
                            has_streamed_content = True
                            send_sse({
                                **meta_template,
                                "choices": [{"index": 0, "delta": {"content": content_piece}, "finish_reason": None}]
                            })
                    elif is_checking_initial_json:
                        initial_check_buffer.append(content_piece)
                        combined = "".join(initial_check_buffer)
                        stripped_comb = combined.strip()

                        # Check for tool call signature (only match when tool name has its closing quote)
                        name_match = re.search(r'\{\s*"(?:name|tool|function|function-name)"\s*:\s*"([a-zA-Z0-9_ -]+)"', combined)
                        if name_match:
                            tool_name = name_match.group(1).strip()
                            if tool_name in valid_tool_names:
                                buffering_tool_call = True
                                tool_call_buffer = list(initial_check_buffer)
                                initial_check_buffer = []
                                is_checking_initial_json = False
                            else:
                                for piece in initial_check_buffer:
                                    send_sse({
                                        **meta_template,
                                        "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]
                                    })
                                has_streamed_content = True
                                initial_check_buffer = []
                                is_checking_initial_json = False
                        else:
                            flush_now = False
                            if stripped_comb.startswith("```"):
                                first_line = stripped_comb.split("\n", 1)[0].lower()
                                lang = first_line[3:].strip()
                                if lang and not lang.startswith("j"):
                                    flush_now = True
                                elif len(combined) > 200 or combined.count("\n") > 4:
                                    flush_now = True
                            elif stripped_comb.startswith("{"):
                                if len(combined) > 100 or "\n\n" in combined:
                                    flush_now = True
                            elif stripped_comb and not (stripped_comb.startswith("{") or stripped_comb.startswith("```")):
                                flush_now = True

                            if flush_now:
                                for piece in initial_check_buffer:
                                    send_sse({
                                        **meta_template,
                                        "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]
                                    })
                                has_streamed_content = True
                                initial_check_buffer = []
                                is_checking_initial_json = False
                    else:
                        send_sse({
                            **meta_template,
                            "choices": [{"index": 0, "delta": {"content": content_piece}, "finish_reason": None}]
                        })

            # Flush initial check buffer if still pending
            if initial_check_buffer:
                for piece in initial_check_buffer:
                    send_sse({
                        **meta_template,
                        "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]
                    })

            # Finalize tool calls or buffered content
            if accumulated_tcs:
                final_tcs = [rewrite_tool_call_entry(accumulated_tcs[k]) for k in sorted(accumulated_tcs.keys())]
                send_sse({
                    **meta_template,
                    "choices": [{"index": 0, "delta": {"tool_calls": final_tcs}, "finish_reason": None}]
                })
                send_sse({
                    **meta_template,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]
                })
            elif tool_call_buffer:
                full_buffered = "".join(tool_call_buffer)
                clean_buffered = re.sub(r"</?tool_call>", "", full_buffered).strip()
                parsed_tc = try_parse_raw_json_tool_call(clean_buffered, valid_tool_names)
                if parsed_tc:
                    prefix, tc_obj = parsed_tc
                    if prefix:
                        send_sse({
                            **meta_template,
                            "choices": [{"index": 0, "delta": {"content": prefix}, "finish_reason": None}]
                        })
                    send_sse({
                        **meta_template,
                        "choices": [{"index": 0, "delta": {"tool_calls": [tc_obj]}, "finish_reason": None}]
                    })
                    send_sse({
                        **meta_template,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]
                    })
                else:
                    send_sse({
                        **meta_template,
                        "choices": [{"index": 0, "delta": {"content": full_buffered}, "finish_reason": None}]
                    })
                    send_sse({
                        **meta_template,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
                    })
            else:
                send_sse({
                    **meta_template,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
                })

            if usage_chunk:
                send_sse(usage_chunk)

            send_sse("[DONE]")
        finally:
            stop_heartbeat.set()
            resp.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenCode Agent Bridge for Local Qwen3-4B + Tor Search")
    parser.add_argument("--host", default=BRIDGE_HOST, help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=BRIDGE_PORT, help="Bind port (default: 61231)")
    args = parser.parse_args()

    # Check if port is already bound
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((args.host, args.port))
        sock.close()
    except OSError:
        # Already running
        sys.exit(0)

    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((args.host, args.port), OpenCodeBridgeHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
