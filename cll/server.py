#!/usr/bin/env python3
"""
cll_server.py - Chat Local LLM (CLL) Gateway Server
Listens on 127.0.0.1:41625.
Reverse-proxies and embeds the authentic llama-ui SvelteKit frontend,
manages local llama-server lifecycle with configurable context and reasoning,
provides zero-log privacy, and seamlessly injects Tor-isolated Web & .onion search.
"""

import os
import sys
import json
import re
import time
import socket
import asyncio
import threading
import argparse
import subprocess
import atexit
from contextlib import asynccontextmanager
from typing import List, Dict, Optional, AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import requests
import uvicorn

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from cll import prompts
from cll import security as security_guard
from cll import page_reader
from cll import search as qwsearch
from cll import verifier


def cleanup_llama_server(force: bool = True):
    """Gracefully terminates llama-server, falling back to SIGKILL if hung."""
    try:
        subprocess.run(["pkill", "-x", "llama-server"], capture_output=True)
        if force:
            time.sleep(0.3)
            if subprocess.run(["pgrep", "-x", "llama-server"], capture_output=True).returncode == 0:
                subprocess.run(["pkill", "-9", "-x", "llama-server"], capture_output=True)
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    yield
    # Cleanup background llama-server on shutdown
    cleanup_llama_server(force=True)


app = FastAPI(title="CLL - Chat Local LLM", lifespan=lifespan)
atexit.register(lambda: cleanup_llama_server(force=True))


def is_local_origin(header_val: Optional[str]) -> bool:
    """Checks if an Origin or Referer header points to localhost / 127.0.0.1."""
    if not header_val:
        return True
    return bool(re.match(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(?::\d+)?(?:/.*)?$", header_val.strip()))


@app.middleware("http")
async def csrf_protection_middleware(request: Request, call_next):
    """Blocks cross-origin state-changing requests (CSRF) to /api/* and /v1/*."""
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        sec_site = request.headers.get("sec-fetch-site")
        if sec_site and sec_site not in ("same-origin", "none"):
            return JSONResponse({"error": "Forbidden: Cross-site request blocked by CSRF guard."}, status_code=403)
        if not is_local_origin(origin) or not is_local_origin(referer):
            return JSONResponse({"error": "Forbidden: Untrusted Origin/Referer blocked by CSRF guard."}, status_code=403)
    return await call_next(request)


LLAMA_URL = "http://127.0.0.1:8080"
LLAMA_UI_DIR = os.path.join(BASE_DIR, "web", "llama-ui")
SHELL_HTML_PATH = os.path.join(BASE_DIR, "web", "cll_shell.html")

MIN_CTX = 2048
MAX_CTX = 49152
CURRENT_CTX = 32768
CURRENT_REASONING = 2
SEARCH_MODE = "deep"   # Default to "deep" (Agentic Tor Research) matching UI
DEEP_READ = True
VERIFIED_MODE = True

AUTO_SEARCH_TRIGGERS = [
    # English triggers
    r"\b(latest|recent|news|current|today|release|status|price|who is|where is|when was)\b",
    r"\b(202[4-9]|203[0-9])\b",
    r"https?://",
    r"(\.onion\b|\bonion\b|hidden\s+service|dark\s*web)",
    r"\b(what is|what are|how to|how does|why is|explain|compare)\b.*\b(change|update|feature|work|version|spec)\b",
    r"\b(research|discover|explore|investigate|analyze|audit|cve|advisory|vulnerability)\b",
    r"\b(search|lookup|find|browse|google|bing|duckduckgo)\b",
    # Turkish triggers
    r"\b(ara|araştır|araştırma|internette|internetten|webde|webden|bul|tara|incele)\b",
    r"\b(haberler|güncel|son\s+dakika|son\s+durum|fiyatı|fiyatları|kimdir|nedir|nelerdir|nasıl)\b",
    r"\b(doküman|belge|versiyon|özellik|özellikleri|tarihi|güvenlik|zafiyet)\b",
    # Command prefixes
    r"^(?:/search|/web|!search|!web|search:|web:|ara:|bul:)\s+"
]

DEFAULT_OFFLINE_PROMPT = (
    "You are an expert, objective technical assistant.\n\n"
    "DIRECTIVES:\n"
    "- Directly answer the user's questions with high accuracy, clarity, and depth.\n"
    "- If the user asks for external information or web research without active search context, "
    "answer directly using your comprehensive internal knowledge base.\n"
    "- NEVER state that you lack web access, internet tools, or browsing capability. "
    "Never apologize for lacking tools, and never output tool refusal disclaimers.\n\n"
    "STYLE & CONCISENESS:\n"
    "- Be direct, concise, and technically dense. Zero fluff, zero chit-chat.\n"
    "- Respond accurately in the language of the user query."
)


CONVERSATIONAL_FOLLOWUPS = [
    r'^(?:bunu\s+|bu\s+cevabı\s+|metni\s+)?(?:türkçeye|türkçe|ingilizceye|ingilizce)\s*(?:ye|e)?\s*(?:çevir|tercüme\s*et|dönüştür)\b',
    r'^(?:translate|translate\s+(?:this|it)?\s*to\s+\w+)\b',
    r'^(?:devam\s*et|devamını\s*yaz|continue|go\s*on|proceed)\b',
    r'^(?:özetle|kısaca\s*anlat|kısalt|summarize|briefly)\b',
    r'^(?:daha\s+(?:fazla\s+)?açıkla|detaylandır|örnek\s*ver|explain\s*more|clarify|give\s*(?:an\s+)?example)\b',
    r'^(?:merhaba|selam|günaydın|iyi\s*günler|hello|hi|hey|thanks|teşekkürler|sağol)\b',
    r'^(?:evet|hayır|tamam|ok|peki|yes|no)\b',
    r'^(?:kodu\s+yaz|koda\s*dök|düzelt|fix|debug|refactor)\b'
]


def is_conversational_followup(query: str) -> bool:
    """Detects pure conversational follow-ups that must never trigger external web search."""
    if not query:
        return True
    q = query.strip().lower()
    if q.startswith(("/search", "/web", "!search", "!web", "search:", "web:", "ara:", "bul:")):
        return False
    if "http://" in q or "https://" in q or ".onion" in q:
        return False
    for pat in CONVERSATIONAL_FOLLOWUPS:
        if re.search(pat, q):
            return True
    return False


def detect_query_language(text: str) -> str:
    """Detects if query is Turkish or English/other."""
    if not text:
        return "en"
    t = text.lower()
    if any(c in t for c in "çğıöşü"):
        return "tr"
    tr_markers = [
        r'\b(?:ve|veya|ile|için|nasıl|nedir|nelerdir|kimdir|neden|niçin|hangisi)\b',
        r'\b(?:ara|araştır|bul|bana|cevap|ver|anlat|açıkla|yaz|özetle|çevir)\b',
        r'\b(?:olan|olarak|kadar|göre|sonra|önce|çünkü|fakat|ama|ancak)\b',
        r'\b(?:parçalarım|yaparım|ederim|edilir|yapılır|parçalanır)\b'
    ]
    for pattern in tr_markers:
        if re.search(pattern, t):
            return "tr"
    return "en"


def sanitize_search_query(q: str) -> str:
    """Cleans foreign grammatical inflection artifacts from search queries."""
    q = re.sub(r'\batomu\b', 'atom', q, flags=re.IGNORECASE)
    q = re.sub(r'\b(uranyumu|çekirdeği|nötronu|protonu|molekülü)\b',
               lambda m: m.group(0)[:-1], q, flags=re.IGNORECASE)
    return q.strip()


def needs_web_search(query: str) -> bool:
    if not query:
        return False
    q_lower = query.lower().strip()
    if is_conversational_followup(q_lower):
        return False
    if q_lower.startswith(("/search", "/web", "!search", "!web", "search:", "web:", "ara:", "bul:")):
        return True
    for pattern in AUTO_SEARCH_TRIGGERS:
        if re.search(pattern, q_lower):
            return True
    if "?" in query and len(query.split()) >= 3:
        return True
    return False


def determine_research_budget(prompt: str, search_mode: str) -> Dict[str, any]:
    """
    Dynamically sizes search sources, query limits, and deep reading scraping depth
    based on prompt intent, technical complexity, and explicit user instructions.
    """
    p_lower = prompt.lower()
    explicit_match = re.search(r'(?:--limit|-n|limit:?)\s*(\d{1,2})|\b(\d{1,2})\s*(?:kaynak|source|sources|makale|paper|papers)\b', p_lower)
    if explicit_match:
        requested = int(explicit_match.group(1) or explicit_match.group(2))
        max_sources = max(3, min(requested, 16))
        return {
            "max_sources": max_sources,
            "per_query_limit": min(6, max(3, max_sources // 2)),
            "deep_read_count": min(6, max(2, max_sources // 2)),
            "academic": True
        }

    deep_signals = [
        r'\b(detaylı|derinlemesine|ayrıntılı|makale|makaleler|akademik|araştır|bilimsel|tez|literatür)\b',
        r'\b(in-depth|exhaustive|academic|papers?|scientific|scholar|comprehensive|literature|mechanism|equations?)\b',
        r'\b(fisyon|füzyon|kuantum|kriptografi|protokol|çekirdek|reaksiyon|fizik|kimya|algoritma)\b'
    ]
    is_deep_research = any(re.search(pat, p_lower) for pat in deep_signals)

    if is_deep_research or search_mode == "deep":
        return {
            "max_sources": 10,
            "per_query_limit": 5,
            "deep_read_count": 4,
            "academic": True
        }

    return {
        "max_sources": 5,
        "per_query_limit": 3,
        "deep_read_count": 2,
        "academic": False
    }


def formulate_research_queries(user_prompt: str) -> List[str]:
    """
    Uses local Qwen3-4B to formulate 1 to 3 concise, keyword-dense search queries (in English)
    for unfamiliar or exploratory topics.
    """
    sys_prompt = prompts.QUERY_PLANNER_SYSTEM_PROMPT
    try:
        r = requests.post(
            f"{LLAMA_URL}/v1/chat/completions",
            json={
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.1,
                "max_tokens": 80,
                "stream": False
            },
            timeout=8.0
        )
        if r.status_code == 200:
            content = r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
            content = re.sub(r"\s*```$", "", content)
            try:
                data = json.loads(content)
                if isinstance(data, list) and data:
                    return [sanitize_search_query(str(q)) for q in data[:3] if q]
            except Exception:
                pass
            matches = re.findall(r'"([^"\n]{3,60})"', content)
            if matches:
                return [sanitize_search_query(m) for m in matches[:3]]
    except Exception:
        pass
    return []


def is_llama_running() -> bool:
    try:
        r = requests.get(f"{LLAMA_URL}/health", timeout=0.8)
        return r.status_code in (200, 503)
    except Exception:
        return subprocess.run(["pgrep", "-x", "llama-server"], capture_output=True).returncode == 0


def get_proxyctl_status() -> Dict[str, any]:
    try:
        res = subprocess.run(["proxyctl", "status", "--json"], capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            tor_info = data.get("tor", {})
            return {
                "ok": True,
                "tor_active": tor_info.get("active", False),
                "tor_ip": tor_info.get("ip", ""),
                "tor_exit": tor_info.get("exit", ""),
                "rotate": tor_info.get("rotate", 0),
                "proxy_addr": data.get("addr", "")
            }
    except Exception:
        pass
    tor_active = qwsearch.check_tor_port()
    return {
        "ok": False,
        "tor_active": tor_active,
        "tor_ip": "",
        "tor_exit": "socks5h",
        "rotate": 0,
        "proxy_addr": ""
    }


# Mount SvelteKit immutable assets
if os.path.isdir(os.path.join(LLAMA_UI_DIR, "_app")):
    app.mount("/_app", StaticFiles(directory=os.path.join(LLAMA_UI_DIR, "_app")), name="app_assets")


@app.get("/")
async def root_handler(raw: Optional[int] = None):
    """
    If raw=1, serve authentic llama-ui HTML for embedding in iframe.
    Otherwise serve cll_shell.html with LLM power bar and Tor controls.
    """
    if raw == 1:
        raw_index = os.path.join(LLAMA_UI_DIR, "index.html")
        if os.path.exists(raw_index):
            return FileResponse(raw_index, media_type="text/html")
        return HTMLResponse("<h3>llama-ui assets not found</h3>", status_code=404)

    if os.path.exists(SHELL_HTML_PATH):
        return FileResponse(SHELL_HTML_PATH, media_type="text/html")
    return HTMLResponse("<h3>cll_shell.html not found</h3>", status_code=404)


@app.get("/favicon.svg")
async def favicon_svg():
    p = os.path.join(LLAMA_UI_DIR, "favicon.svg")
    if os.path.exists(p):
        return FileResponse(p, media_type="image/svg+xml")
    return Response(status_code=404)


@app.get("/manifest.webmanifest")
async def manifest_webmanifest():
    p = os.path.join(LLAMA_UI_DIR, "manifest.webmanifest")
    if os.path.exists(p):
        return FileResponse(p, media_type="application/manifest+json")
    return Response(status_code=404)


@app.get("/cll-wipe")
async def wipe_handler():
    """Helper iframe endpoint to wipe origin localStorage, sessionStorage, and IndexedDB."""
    html = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body>
<script>
  (async function() {
    try {
      localStorage.clear();
      sessionStorage.clear();
      if (window.indexedDB && window.indexedDB.databases) {
        const dbs = await window.indexedDB.databases();
        for (const db of dbs) {
          if (db.name) window.indexedDB.deleteDatabase(db.name);
        }
      }
    } catch(e) {}
  })();
</script>
</body>
</html>"""
    return HTMLResponse(html)


# API endpoints
@app.get("/api/status")
async def api_status():
    status = get_proxyctl_status()
    status["llama_ready"] = is_llama_running()
    status["ctx"] = CURRENT_CTX
    status["reasoning"] = CURRENT_REASONING
    status["search_mode"] = SEARCH_MODE
    status["deep_read"] = DEEP_READ
    status["verified_mode"] = VERIFIED_MODE
    return JSONResponse(status)


@app.post("/api/settings")
async def api_settings(request: Request):
    global SEARCH_MODE, DEEP_READ, VERIFIED_MODE
    data = await request.json()
    if "search_mode" in data:
        SEARCH_MODE = str(data["search_mode"])
    if "deep_read" in data:
        DEEP_READ = bool(data["deep_read"])
    if "verified_mode" in data:
        VERIFIED_MODE = bool(data["verified_mode"])
    return JSONResponse({"ok": True, "search_mode": SEARCH_MODE, "deep_read": DEEP_READ, "verified_mode": VERIFIED_MODE})


@app.post("/api/tor/newip")
async def api_tor_newip():
    output = ""
    success = False
    try:
        res = subprocess.run(["proxyctl", "tor", "newip"], capture_output=True, text=True, timeout=8)
        if res.returncode == 0:
            success = True
            output = res.stdout.strip()
    except Exception:
        pass

    if not success:
        try:
            success = qwsearch.rotate_tor_circuit()
            output = "Tor circuit rotated successfully" if success else "Tor Control Port signal failed"
        except Exception as e:
            output = str(e)

    status = get_proxyctl_status()
    return JSONResponse({"success": success, "status": status, "output": output})


@app.post("/api/llm/start")
async def api_llm_start(request: Request):
    global CURRENT_CTX, CURRENT_REASONING
    data = await request.json()
    raw_ctx = int(data.get("ctx", CURRENT_CTX))
    ctx = max(MIN_CTX, min(raw_ctx, MAX_CTX))
    reasoning = int(data.get("reasoning", CURRENT_REASONING))

    CURRENT_CTX = ctx
    CURRENT_REASONING = reasoning

    # Stop any existing llama-server process (SIGTERM with SIGKILL fallback)
    cleanup_llama_server(force=True)
    await asyncio.sleep(0.3)

    # Determine reasoning flags
    r_flags = {
        0: ["--reasoning", "off"],
        1: ["--reasoning", "on", "--reasoning-effort", "low"],
        2: ["--reasoning", "on", "--reasoning-effort", "medium"],
        3: ["--reasoning", "on", "--reasoning-effort", "high"],
        4: ["--reasoning", "on", "--reasoning-effort", "max"]
    }.get(reasoning, ["--reasoning", "on", "--reasoning-effort", "medium"])

    # Launch qwen-local server in detached background process with zero logging
    env = os.environ.copy()
    env["CTX"] = str(ctx)
    env["PORT"] = "8080"

    cmd = [
        os.path.join(BASE_DIR, "qwen-local"),
        "server",
        "--log-disable"
    ] + r_flags

    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True
    )

    # Wait for llama-server to become healthy (up to 15s)
    ready = False
    err_detail = ""
    for _ in range(30):
        await asyncio.sleep(0.5)
        if proc.poll() is not None and proc.returncode != 0:
            try:
                err_detail = proc.stderr.read().decode("utf-8", errors="ignore").strip()[-400:]
            except Exception:
                pass
            break
        if is_llama_running():
            ready = True
            break

    return JSONResponse({
        "ready": ready,
        "ctx": CURRENT_CTX,
        "reasoning": CURRENT_REASONING,
        "error": err_detail if not ready else ""
    })


@app.post("/api/llm/stop")
async def api_llm_stop():
    cleanup_llama_server(force=True)
    await asyncio.sleep(0.3)
    return JSONResponse({"ready": is_llama_running()})


# Proxy /props and /v1/models (fallback to static files if server is offline)
@app.get("/props")
async def proxy_props():
    if is_llama_running():
        try:
            r = requests.get(f"{LLAMA_URL}/props", timeout=1.5)
            if r.status_code == 200:
                return JSONResponse(r.json())
        except Exception:
            pass

    fallback_path = os.path.join(LLAMA_UI_DIR, "default_props.json")
    if os.path.exists(fallback_path):
        with open(fallback_path, "r", encoding="utf-8") as f:
            props = json.load(f)
            props["default_generation_settings"]["n_ctx"] = CURRENT_CTX
            return JSONResponse(props)
    return JSONResponse({"default_generation_settings": {"n_ctx": CURRENT_CTX}, "total_slots": 1})


@app.get("/v1/models")
async def proxy_models():
    if is_llama_running():
        try:
            r = requests.get(f"{LLAMA_URL}/v1/models", timeout=1.5)
            if r.status_code == 200:
                return JSONResponse(r.json())
        except Exception:
            pass

    fallback_path = os.path.join(LLAMA_UI_DIR, "default_models.json")
    if os.path.exists(fallback_path):
        with open(fallback_path, "r", encoding="utf-8") as f:
            return JSONResponse(json.load(f))
    return JSONResponse({"models": [], "object": "list", "data": []})


@app.get("/slots")
@app.get("/health")
@app.post("/tokenize")
@app.post("/detokenize")
async def proxy_pass_through(request: Request):
    if not is_llama_running():
        return JSONResponse({"error": "LLM offline"}, status_code=503)
    path = request.url.path
    try:
        if request.method == "GET":
            r = requests.get(f"{LLAMA_URL}{path}", timeout=2.0)
            return JSONResponse(r.json(), status_code=r.status_code)
        else:
            body = await request.json()
            r = requests.post(f"{LLAMA_URL}{path}", json=body, timeout=4.0)
            return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# OpenAI Chat Completion Interceptor with Tor Web / .onion Search
async def completion_stream(
    payload: dict,
    search_summary_md: Optional[str] = None,
    verified_mode: bool = False,
    query_lang: str = "tr"
) -> AsyncGenerator[str, None]:
    if search_summary_md:
        initial_chunk = {
            "choices": [{
                "index": 0,
                "delta": {"content": search_summary_md + "\n\n"},
                "finish_reason": None
            }]
        }
        yield f"data: {json.dumps(initial_chunk)}\n\n"

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _stream_worker():
        try:
            with requests.post(
                f"{LLAMA_URL}/v1/chat/completions",
                json=payload,
                stream=True,
                timeout=120
            ) as req:
                for line in req.iter_lines():
                    if not line:
                        continue
                    loop.call_soon_threadsafe(queue.put_nowait, line.decode("utf-8", errors="ignore"))
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=_stream_worker, daemon=True).start()

    if not verified_mode:
        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                err_chunk = {
                    "choices": [{
                        "index": 0,
                        "delta": {"content": f"\n\n**Error:** LLM connection error: {str(item)}"},
                        "finish_reason": "error"
                    }]
                }
                yield f"data: {json.dumps(err_chunk)}\n\n"
                yield "data: [DONE]\n\n"
                break
            if item.startswith("data: "):
                yield f"{item}\n\n"
                if item[6:].strip() == "[DONE]":
                    break
    else:
        full_text_parts = []
        has_error = None
        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                has_error = item
                break
            if item.startswith("data: "):
                raw_payload = item[6:].strip()
                if raw_payload == "[DONE]":
                    break
                try:
                    chunk_obj = json.loads(raw_payload)
                    delta_content = chunk_obj.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta_content:
                        full_text_parts.append(delta_content)
                except Exception:
                    pass

        if has_error:
            err_chunk = {
                "choices": [{
                    "index": 0,
                    "delta": {"content": f"\n\n**Error:** LLM connection error: {str(has_error)}"},
                    "finish_reason": "error"
                }]
            }
            yield f"data: {json.dumps(err_chunk)}\n\n"
            yield "data: [DONE]\n\n"
            return

        full_text = "".join(full_text_parts)
        verified_text = verifier.correct_terminology_and_logic(full_text, lang=query_lang)

        # Progressive slice streaming to UI
        chunk_size = 40
        for i in range(0, len(verified_text), chunk_size):
            slice_text = verified_text[i:i + chunk_size]
            c = {
                "choices": [{
                    "index": 0,
                    "delta": {"content": slice_text},
                    "finish_reason": None
                }]
            }
            yield f"data: {json.dumps(c)}\n\n"

        done_chunk = {
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }]
        }
        yield f"data: {json.dumps(done_chunk)}\n\n"
        yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions_handler(request: Request):
    if not is_llama_running():
        async def offline_stream():
            msg = "⚠️ **Local LLM Offline.**\n\nPlease click **'LLM Offline (Start)'** on the top control bar to launch the model."
            chunk = {"choices": [{"index": 0, "delta": {"content": msg}, "finish_reason": "stop"}]}
            yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(offline_stream(), media_type="text/event-stream")

    data = await request.json()
    messages = data.get("messages", [])

    # Strip control tokens from user input
    for m in messages:
        if "content" in m and isinstance(m["content"], str):
            m["content"] = security_guard.strip_control_tokens(m["content"])

    last_user_msg = ""
    for m in reversed(messages):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            last_user_msg = m.get("content", "")
            break

    query_lang = detect_query_language(last_user_msg)
    is_followup = is_conversational_followup(last_user_msg)
    context_info = verifier.resolve_conversation_context(messages)

    do_search = False
    if not is_followup:
        if SEARCH_MODE in ("always", "deep"):
            do_search = True
        elif SEARCH_MODE == "auto":
            do_search = needs_web_search(last_user_msg)

    sources = []
    deep_pages = []
    engine_name = "None"
    search_summary_md = None
    generated_queries = []

    if do_search and last_user_msg:
        if not qwsearch.check_tor_port():
            async def opsec_err():
                err_msg = "🛑 **[OPSEC FAIL-CLOSED]** Tor SOCKS5h (`127.0.0.1:9050`) is offline. Web search and outbound connections blocked."
                c = {"choices": [{"index": 0, "delta": {"content": err_msg}, "finish_reason": "stop"}]}
                yield f"data: {json.dumps(c)}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(opsec_err(), media_type="text/event-stream")

        loop = asyncio.get_event_loop()

        # 1. Direct URLs (HTTP/HTTPS and raw .onion)
        explicit_urls = re.findall(r'https?://[^\s<>"]+', last_user_msg)
        raw_onions = re.findall(r'\b(?:[a-z2-7]{56}|[a-z0-9-]{16,56})\.onion(?:/[^\s<>"]*)?', last_user_msg, re.IGNORECASE)
        for ro in raw_onions:
            formatted_onion = f"http://{ro}"
            if not any(ro in u for u in explicit_urls):
                explicit_urls.append(formatted_onion)

        for target_url in explicit_urls[:2]:
            scraped = await loop.run_in_executor(None, page_reader.fetch_page_text_tor, target_url, 4500)
            if scraped and scraped.get("text"):
                deep_pages.append(scraped)
                sources.append({
                    "title": scraped.get("title") or target_url,
                    "url": target_url,
                    "snippet": scraped["text"][:300].replace('\n', ' '),
                    "engine": "Tor Direct Scrape"
                })
                engine_name = "Tor Direct Scrape"

        # Determine dynamic research budget based on prompt and mode
        budget = determine_research_budget(last_user_msg, SEARCH_MODE)
        max_sources = budget["max_sources"]
        per_query_limit = budget["per_query_limit"]
        deep_read_target = budget["deep_read_count"]

        # 2. Agentic Multi-Query or Standard Search Cascade
        wants_onion = bool(re.search(r'(\.onion|\bonion\b|hidden\s+service|dark\s*web)', last_user_msg, re.IGNORECASE))
        is_exploratory = (SEARCH_MODE == "deep") or bool(re.search(
            r'\b(research|discover|explore|investigate|explain|what is|how does|features|versions?)\b',
            last_user_msg,
            re.IGNORECASE
        ))

        search_prompt = re.sub(r"^(?:/search|/web|!search|!web|search:|web:|ara:|bul:)\s+", "", last_user_msg, flags=re.IGNORECASE).strip() or last_user_msg

        if context_info.get("has_history") and len(search_prompt.split()) <= 4 and context_info.get("last_topic"):
            enriched_prompt = f"{context_info['last_topic']} {search_prompt}"
        else:
            enriched_prompt = search_prompt

        if not deep_pages and (is_exploratory and not explicit_urls):
            generated_queries = await loop.run_in_executor(None, formulate_research_queries, enriched_prompt)

        # Verified Mode: Augment with multi-hop factual sub-queries to eliminate reasoning amnesia
        if VERIFIED_MODE and not deep_pages and (is_exploratory and not explicit_urls):
            decomposed = verifier.decompose_reasoning_query(search_prompt, query_lang)
            for dq in decomposed:
                if dq not in generated_queries:
                    generated_queries.append(dq)

        if not deep_pages and generated_queries:
            engine_name = f"Agentic Research ({len(generated_queries)} queries)"
            existing_urls = {s["url"] for s in sources}
            for q in generated_queries:
                q_onion = wants_onion or bool(re.search(r'(\.onion|\bonion\b|hidden\s+service)', q, re.IGNORECASE))
                if q_onion:
                    q_res = await loop.run_in_executor(None, qwsearch.search_ahmia_onion, q, per_query_limit)
                else:
                    q_res, _ = await loop.run_in_executor(None, qwsearch.execute_search_cascade, q, per_query_limit)
                for r in q_res:
                    if r.get("url") not in existing_urls:
                        sources.append(r)
                        existing_urls.add(r.get("url"))

        # Fallback to standard regex query if agentic loop generated no queries
        if not deep_pages and not sources and (not explicit_urls):
            clean_query = search_prompt
            for u in explicit_urls:
                clean_query = clean_query.replace(u, "")
            for ro in raw_onions:
                clean_query = clean_query.replace(ro, "")
            clean_query = re.sub(
                r'\b(in the page|from site|on website|looking for|search for|about|steps|how to|what is|tell me|explain|summarize|briefly|details|which|list|security|features|project|management)\b',
                '', clean_query, flags=re.IGNORECASE
            )
            clean_query = re.sub(
                r'\b(web\s*de|web\s*den|webde|webden|internette|internetten|ara|araştır|araştırma|bul|bana|hakkında|bilgi|ver|nedir|nelerdir|nasıl|sen|cevap\s*ver|cevap|en\s+basit|basitçe|basit|lütfen)\b',
                '', clean_query, flags=re.IGNORECASE
            )
            clean_query = re.sub(r'(\.onion|\bonion\b|hidden\s+service\w*|dark\s*web\w*)', '', clean_query, flags=re.IGNORECASE)
            clean_query = re.sub(r'[?!.,;:\"\'`]+', ' ', clean_query)
            clean_query = sanitize_search_query(clean_query)
            clean_query = re.sub(r'\s+', ' ', clean_query).strip()

            search_term = clean_query if clean_query else search_prompt
            if wants_onion and not explicit_urls:
                results = await loop.run_in_executor(None, qwsearch.search_ahmia_onion, search_term, max_sources)
                engine_used = "Ahmia (.onion Discovery)"
            else:
                results, engine_used = await loop.run_in_executor(None, qwsearch.execute_search_cascade, search_term, max_sources)

            existing_urls = {s["url"] for s in sources}
            for r in results:
                if r.get("url") not in existing_urls:
                    sources.append(r)
                    existing_urls.add(r.get("url"))

            if engine_name == "None":
                engine_name = engine_used

        # Technical specification enrichment for cryptography / protocol queries
        tech_keywords = re.findall(r'\b(ed25519|curve25519|rsa|aes|crypt\w*|protocol\w*|rendezvous|handshake|hidden\s*service\w*|onion\s*v3|private\s*key)\b', last_user_msg, re.IGNORECASE)
        if tech_keywords and not explicit_urls:
            target_term = "Tor (network)" if any("onion" in k.lower() or "hidden" in k.lower() for k in tech_keywords) else tech_keywords[0]
            if "ed25519" in [k.lower() for k in tech_keywords]:
                target_term = "Ed25519"
            wiki_spec = await loop.run_in_executor(None, qwsearch.fetch_wikipedia_summary, target_term)
            if wiki_spec and wiki_spec.get("url") not in existing_urls:
                sources.insert(0, wiki_spec)
                existing_urls.add(wiki_spec.get("url"))

        sources = sources[:max_sources]

        # Deep reading for top search candidates
        if (DEEP_READ or wants_onion or is_exploratory) and not explicit_urls and sources:
            candidates = [c.get("url") for c in sources[:deep_read_target] if c.get("url", "").startswith("http")]
            if candidates:
                tasks = [
                    loop.run_in_executor(None, page_reader.fetch_page_text_tor, u, 3500, 14)
                    for u in candidates
                ]
                for coro in asyncio.as_completed(tasks):
                    scraped = await coro
                    if scraped and scraped.get("text"):
                        deep_pages.append(scraped)
                        if len(deep_pages) >= (deep_read_target // 2 + 1):
                            break

        sandboxed_data, injection_detected, warnings = security_guard.build_sandboxed_context(
            last_user_msg, sources, deep_pages
        )

        if sources or deep_pages:
            badge_items = []
            for idx, s in enumerate(sources, 1):
                badge_items.append(f"{idx}. [{s.get('title')}]({s.get('url')})")
            sources_list_md = "\n".join(badge_items)

            deep_tag = " + 📖 Deep Read" if deep_pages else ""
            alert_md = "\n> 🛡️ **Security Notice:** Suspicious prompt injection payload detected and sanitized.\n" if injection_detected else ""

            queries_md = ""
            if generated_queries:
                queries_md = "**🔍 Agent-Generated Search Queries:**\n" + "\n".join(f"- `{q}`" for q in generated_queries) + "\n\n"

            search_summary_md = (
                f"### 🌐 Tor Sources ({engine_name} - {len(sources)} results{deep_tag})\n\n"
                f"{queries_md}"
                f"**📚 Cited Sources:**\n"
                f"{sources_list_md}\n"
                f"{alert_md}"
                f"\n---\n"
            )

            if wants_onion:
                sys_instruction = f"{prompts.DARK_WEB_RESEARCHER_PROMPT}\n\n{sandboxed_data}"
            else:
                sys_instruction = f"{prompts.STANDARD_ASSISTANT_PROMPT}\n\n{sandboxed_data}"

            lang_directive = (
                "\n\n🚨 DİL ZORUNLULUĞU (MANDATORY LANGUAGE DIRECTIVE):\n"
                "Kullanıcı Türkçe talimat vermiştir. Yanıtınızın TAMAMINI (tüm başlıklar, açıklamalar, analizler ve sonuçlar) EKSİKSİZ TÜRKÇE olarak yazın.\n"
                "Alıntılanan kaynaklar İngilizce olsa dahi bilgileri Türkçe açıklayın. Kullanıcı açıkça talep etmedikçe ASLA İngilizce yanıt vermeyin."
                if query_lang == "tr" else ""
            )
            sys_instruction += lang_directive

            if context_info.get("has_history") and context_info.get("summary"):
                sys_instruction += f"\n\n### 💬 Conversation Context:\n{context_info['summary']}"

            filtered = [m for m in messages if m.get("role") != "system"]
            data["messages"] = [{"role": "system", "content": sys_instruction}] + filtered
        else:
            # When web search was attempted over Tor but returned no results
            fallback_instruction = (
                f"{prompts.STANDARD_ASSISTANT_PROMPT}\n\n"
                f"### System Notice\n"
                f"An anonymous Tor web search was conducted for '{search_prompt}', but no external search hits were retrieved on the current Tor circuit.\n"
                f"Directly answer the user's inquiry with your internal knowledge with high precision.\n"
                f"NEVER claim to lack internet tools, never apologize, and never output tool refusal statements."
            )
            lang_directive = (
                "\n\n🚨 DİL ZORUNLULUĞU (MANDATORY LANGUAGE DIRECTIVE):\n"
                "Kullanıcı Türkçe talimat vermiştir. Yanıtınızın TAMAMINI (tüm başlıklar, açıklamalar, analizler ve sonuçlar) EKSİKSİZ TÜRKÇE olarak yazın.\n"
                "Kullanıcı açıkça talep etmedikçe ASLA İngilizce yanıt vermeyin."
                if query_lang == "tr" else ""
            )
            fallback_instruction += lang_directive
            filtered = [m for m in messages if m.get("role") != "system"]
            data["messages"] = [{"role": "system", "content": fallback_instruction}] + filtered
    else:
        # Guarantee default technical system prompt to eliminate tool-refusal hallucinations
        has_system = any(m.get("role") == "system" for m in messages)
        lang_prompt = (
            "\n\n🚨 DİL ZORUNLULUĞU (MANDATORY LANGUAGE DIRECTIVE):\n"
            "Kullanıcı Türkçe talimat vermiştir. Yanıtınızı EKSİKSİZ TÜRKÇE olarak verin. Asla İngilizce yanıt vermeyin."
            if query_lang == "tr" else ""
        )
        if not has_system:
            data["messages"] = [{"role": "system", "content": DEFAULT_OFFLINE_PROMPT + lang_prompt}] + messages
        else:
            for m in data["messages"]:
                if m.get("role") == "system":
                    m["content"] += f"\n\nNote: Answer directly using internal knowledge. Never state that you lack web access.{lang_prompt}"

    return StreamingResponse(
        completion_stream(data, search_summary_md, verified_mode=VERIFIED_MODE, query_lang=query_lang),
        media_type="text/event-stream"
    )


def main():
    parser = argparse.ArgumentParser(description="CLL - Chat Local LLM Gateway Server")
    parser.add_argument("--port", type=int, default=41625, help="Port to bind CLL server (default: 41625)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open browser on startup")
    args = parser.parse_args()

    # If port is held by a previous instance, terminate stale instance
    curr_pid = os.getpid()
    test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        test_sock.bind((args.host, args.port))
        test_sock.close()
    except OSError as e:
        if e.errno == 98:
            sys.stderr.write(f"[CLL] Port {args.port} is already busy. Terminating stale CLL instance...\n")
            try:
                out = subprocess.check_output(["pgrep", "-f", "cll\\.server|cll/server\\.py"], text=True)
                for pid_str in out.strip().split():
                    pid = int(pid_str)
                    if pid != curr_pid:
                        os.kill(pid, signal.SIGTERM)
                for _ in range(25):
                    time.sleep(0.1)
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        s.bind((args.host, args.port))
                        s.close()
                        break
                    except OSError:
                        pass
            except Exception:
                pass

    # Guarantee cold start: Ensure LLM is OFF on startup (0 VRAM used until user explicitly toggles on)
    cleanup_llama_server(force=True)

    print("═══════════════════════════════════════════════════════════════")
    print(f" ⚡ CLL — Chat Local LLM (Port: {args.port})")
    print(f" 🌐 UI:        http://{args.host}:{args.port}")
    print(f" 🧠 LLM URL:   {LLAMA_URL} (Controlled via Power Bar — Default: OFF)")
    print(" 🧅 Tor OPSEC: Fail-Closed SOCKS5h (127.0.0.1:9050)")
    print(" 🛡️  Security: Multi-layer prompt injection filter & read-only")
    print(" 🧅 .onion:    Native hidden service discovery & scraping")
    print(" 🧹 Privacy:   Zero disk logging (--log-disable) & storage wipe")
    print(" 🛑 Stop:      Press Ctrl+C to stop (Ctrl+Z to background)")
    print("═══════════════════════════════════════════════════════════════")

    # Automatically open browser once server is bound
    if not args.no_browser:
        def _auto_open_browser():
            time.sleep(0.6)
            ui_url = f"http://{args.host}:{args.port}"
            try:
                subprocess.Popen(["xdg-open", ui_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                try:
                    import webbrowser
                    webbrowser.open(ui_url)
                except Exception:
                    pass
        import threading
        threading.Thread(target=_auto_open_browser, daemon=True).start()

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        cleanup_llama_server(force=True)
        print("\n[CLL] Server stopped. Background resources released.")


if __name__ == "__main__":
    main()
