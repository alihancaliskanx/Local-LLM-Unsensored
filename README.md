# Local LLM (CLL) Multi-Model Inference & Privacy Platform

Local inference configuration, unified CLI runner (`cll`), and privacy-preserving toolchain using `llama.cpp` on Arch Linux / CachyOS, optimized for 4 GB VRAM + 16 GB RAM. The framework supports both unrestricted (abliterated) models and clean, aligned coding/debugging models (e.g., `Qwen2.5-Coder-3B-Instruct`), while strictly maintaining Tor SOCKS5h privacy boundaries.

---

## 1. Multi-Model Support & Hardware Alignment

The suite is model-agnostic: it supports official aligned code/instruct models, reasoning models, and abliterated models. Abliterated checkpoints remove refusal vectors for security and reverse-engineering research, while official aligned models offer maximum syntax precision and benchmark performance for programming and debugging.

### Supported Model Profiles (4 GB VRAM Tier)

| Model Profile | Base Weights | Role | Context | VRAM Footprint |
| :--- | :--- | :--- | :--- | :--- |
| `qwen3-4b` | `Huihui-Qwen3-4B-Instruct-2507-abliterated` | Uncensored flagship / OSINT / bypass analysis | 32K | ~2.5 GB (fits in VRAM) |
| `qwen2.5-coder-3b` | `Qwen2.5-Coder-3B-Instruct` | Clean code & debug flagship (84.1% HumanEval) | 32K | ~1.93 GB (100% GPU, ~65 tok/s) |
| `deepseek-r1-1.5b` | `DeepSeek-R1-Distill-Qwen-1.5B` | Ultra-fast reasoning & math analysis | 32K | ~1.1 GB (100% GPU, >80 tok/s) |
| `qwen2.5-coder-7b` | `Qwen2.5-Coder-7B-Instruct` | Heavy architecture & complex refactoring | 16K | ~4.7 GB (hybrid GPU+CPU split) |

Switch between profiles instantly using `cll model use <id>` or pass `-m <id>` to any `cll` command.

### Benchmark on 4 GB VRAM

RTX 3050 Ti Laptop (4 GB), 16 GB RAM, 6 cores, default launcher settings, temperature 0.2. Nine Python tasks (two prompted in Turkish), each checked by automated tests, one attempt per task.

| Model | Tasks Passed | Generation Speed | Notes |
| :--- | :--- | :--- | :--- |
| `Huihui-Qwen3-4B-Instruct-2507-abliterated` `i1-Q4_K_M` | **8/9** | **~54 tok/s** | Fastest and most accurate |
| `glm-4-9b-chat-abliterated` `Q4_K_M` | 6/9 | ~8 tok/s | Previous default; split between GPU and CPU |
| `Huihui-Qwen3.5-9B-abliterated` `Q4_K_M` | 6/9 | ~10 tok/s | Thinking disabled; one task looped inside code comments until the token limit |
| `Huihui-Qwen3.5-4B-abliterated` `Q4_K_M` | 5/9 | ~46 tok/s | Thinking enabled; often writes `’` instead of `'` in Python code |

Abliteration slightly weakens reasoning; a newer base model does not guarantee a better abliterated model.

---

## 2. Native `llama.cpp` vs. Docker on 4 GB VRAM Systems

When running `Huihui-Qwen3-4B-Instruct-2507-abliterated.i1-Q4_K_M.gguf` (~2.5 GB) on a system with 4 GB VRAM and 16 GB RAM, the model only just fits: with the default 8192 context and 512 MiB margin, about 32 of its 37 layers go to the GPU and the rest run from system RAM. Native execution is strongly preferred over Docker in constrained VRAM environments:

| Criterion | Native (`llama.cpp`) | Docker (`nvidia-container-toolkit`) |
| :--- | :--- | :--- |
| **VRAM Overhead** | Minimal; all free VRAM outside the desktop session is available for model layers. | Container runtime and CUDA context overhead consume an extra 150–300 MB VRAM (2–5 fewer GPU layers). |
| **CPU Performance** | Offloaded CPU layers execute directly with host AVX2 / AVX-512 instruction sets. | Namespace virtualization introduces minor memory bandwidth overhead. |
| **Footprint** | Single binary (`llama-server` or `llama-cli`), no background daemon required. | Requires `nvidia-container-toolkit` and 5–8 GB CUDA container images. |

---

## 3. Repository Structure

| Path | Description |
| :--- | :--- |
| `setup.sh` | One-time setup: installs `llama.cpp`, downloads the model, and links `cll`, `qwen-local`, `torsearch`, `qstop`, and `cll-reaper` into `~/.local/bin` |
| `bin/cll` | Unified CLI entry point: server, chat, stop, search, model management, and doctor diagnostics |
| `models.json` | Multi-model manifest defining parameters, contexts, VRAM fit margins, and HuggingFace repositories |
| `cll/model_manager.py` | Multi-model profile manager for listing, switching, and downloading GGUF models |
| `qwen-local` | Command entry point: dispatches `server`, `cli`, and `stop` to `scripts/` (retained for backward compatibility) |
| `torsearch` | Fast standalone CLI launcher for privacy-preserving raw Tor search used by OpenCode and scripts |
| `opencode.json` | Preconfigured OpenCode agent definition file (local provider, autonomous Tor tools, and policies) |
| `tools/cll-reaper/` | Minimal (2.4 MB RAM) Rust watchdog daemon, on-demand lazy starter, authentication gateway, and idle VRAM reaper |
| `scripts/cll-reaper.service` | User-level systemd service definition for automatic background cll-reaper management |
| `scripts/qstop` | Standalone process terminator safely shutting down active `llama-server`, `llama-cli`, and `opencode_bridge` |
| `qwen.zsh` | Shell entry point sourcing modular helper scripts under `shell/` |
| `shell/core.zsh` | Shared context/reasoning resolvers (`32K` default, `48K` ceiling) and shell helper functions |
| `shell/cli.zsh` | Terminal functions (`qwserver`, `qwcli`, `qwfile`, `qwsec`, `qwpipe`) using `-f` file input to bypass the 128 KiB kernel argument limit |
| `shell/web.zsh` | Tor web search (`qwsearch`) and Chat Local LLM (`cll`) launchers |
| `scripts/common.sh` | Shared runtime defaults (`CTX=32768`, `-ctk q4_0 -ctv q4_0`) and GPU/binary checks |
| `scripts/run-server.sh` | Launches `llama-server` on `127.0.0.1:61232` and background `cll.opencode_bridge` on `127.0.0.1:61231` |
| `scripts/run-cli.sh` | Launches interactive or single-turn chat via `llama-cli` (loads `prompts/cli_rules.md`) |
| `scripts/pre-commit` | Git pre-commit hook scanning diffs for secrets and security flaws via active server or CLI |
| `cll/opencode_bridge.py` | Lightweight OpenAI-compatible gateway (`127.0.0.1:61231`) for OpenCode with prompt pruning and Tor search injection |
| `cll/inference.py` | Unified terminal inference engine routing CLI commands to active server HTTP or CLI fallback |
| `cll/project_analyzer.py` | Hierarchical codebase explorer & chunked module analyst with `/tmp/local-llm/` note-taking |
| `cll/symbol_resolver.py` | In-memory C/C++ `#include` and Python `import` symbol table resolver with relevance filtering |
| `cll/server.py` | Chat Local LLM (CLL) FastAPI gateway (`127.0.0.1:41625`) with CSRF guard and non-blocking streaming |
| `cll/search.py` | Privacy-preserving, Tor-only web & `.onion` search engine with Fail-Closed OPSEC |
| `cll/page_reader.py` | Safe, Tor-only webpage, `.onion`, and GitHub/GitLab raw README extractor |
| `cll/security.py` | Multi-layer prompt injection defense and escaped XML untrusted-data sandboxing |
| `cll/prompts.py` | System prompt templates for OSINT/dark web research, standard synthesis, and query planning |
| `cll_server.py` | Compatibility shim delegating to `cll.server` |
| `qwsearch.py` | Compatibility shim delegating to `cll.search` |
| `prompts/cli_rules.md` | System prompt rules configuring terminal `llama-cli` for direct developer responses |
| `web/cll_shell.html` | CLL top control bar (power toggle, 4K–48K token selector, Tor status/IP rotation, storage wipe) |
| `web/llama-ui/` | Embedded upstream `llama-ui` SvelteKit static bundle |
| `man/man1/` | Section 1 UNIX manual pages (`qwfile.1`, `qwsec.1`, `qwpipe.1`, `qwcli.1`, `qwserver.1`) |
| `guide/` | Operational security and anonymous technical research guides |
| `tests/test_suite.py` | Automated unit test suite covering symbol resolution, project analyzer, sandbox escaping, and CSRF |
| `.gitignore` | Excludes `*.gguf` model weights, partial downloads, Python bytecode, and runtime logs |

---

## 4. Installation (Arch Linux / CachyOS)

### Quick Setup

```bash
./setup.sh
```

`setup.sh` performs every step below and skips the ones already done, so it is safe to run again:

1. Installs `llama-cpp` with `ggml-cuda` (if `nvidia-smi` is present) or `ggml-vulkan` via `pacman`. Set `BACKEND=cuda` or `BACKEND=vulkan` to choose explicitly.
2. Downloads `Huihui-Qwen3-4B-Instruct-2507-abliterated.i1-Q4_K_M.gguf` from `mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-i1-GGUF` into the project root (or `MODEL_PATH`). An interrupted download resumes on the next run.
3. Links the `qwen-local` and `torsearch` commands into `~/.local/bin` (or `BIN_DIR`). Existing links that point elsewhere are never overwritten.

Remove the `qwen-local` and `torsearch` links again with `./setup.sh --uninstall`; installed packages and the model are kept.

The manual steps are listed below for reference.

Modern Arch Linux and CachyOS repositories provide prebuilt `llama-cpp` packages with modular `ggml` backends:

### Option A: CUDA Backend (Maximum NVIDIA Performance)

```bash
sudo pacman -S --needed llama-cpp ggml-cuda
```

### Option B: Vulkan Backend (Lightweight Alternative Without CUDA Toolkit)

```bash
sudo pacman -S --needed llama-cpp ggml-vulkan
```

### Model Placement

Place `Huihui-Qwen3-4B-Instruct-2507-abliterated.i1-Q4_K_M.gguf` in the project root directory, or specify a custom location via the `MODEL_PATH` environment variable.

---

## 5. Usage

After `setup.sh`, `cll` works from any directory as the primary interface (with `qwen-local` retained for compatibility). Without global links, `bin/cll`, `./run-server.sh`, and `./run-cli.sh` take the same arguments and environment variables.

### A. Local Web UI and OpenAI API Server

```bash
cll server
```

- **OpenAI API Gateway (Lazy-Start & Auth):** `http://127.0.0.1:61230/v1` (via `cll-reaper`)
- **Direct LLAMA Server Endpoint & Web UI:** `http://127.0.0.1:61232` / `http://127.0.0.1:61232/v1`
- **Agent Bridge (Pruning & Tor Injection):** `http://127.0.0.1:61231/v1`

Override runtime parameters with environment variables when needed:

```bash
NGL=20 CTX=4096 PORT=61232 cll server
```

### B. Interactive Terminal Chat

```bash
cll chat
```

Or target any model directly without altering your default configuration:

```bash
cll -m qwen2.5-coder-3b chat
```

If a custom `rules.md` file exists in the repository root (or is pointed to via `RULES_PATH`), `cll chat` automatically injects it as the system prompt using `-sysf`.

Only one `llama-server` or `llama-cli` instance can hold the GPU at a time. If another one is running, `qwen-local` waits up to 5 seconds for it to exit and then stops with the PIDs to terminate.

### C. Shell Functions (`qwen.zsh`)

Load the helper functions into your shell profile (`~/.zshrc`):

```bash
[[ -f "$HOME/Local-LLM-Unsensored/qwen.zsh" ]] && source "$HOME/Local-LLM-Unsensored/qwen.zsh"
```

The shell integration provides high-performance developer commands with automatic context scaling, reasoning effort control, Tor privacy, and in-memory symbol resolution:

| Command | Shorthand | Description | Primary Example |
| :--- | :--- | :--- | :--- |
| `qwfile` | — | File, codebase, repository, and URL analyzer with RAM symbol resolution | `qwfile -c 32 -r 3 src/ "Analyze system architecture"` |
| `qwsec` | — | Security audit and CWE/OWASP vulnerability scanner (with `--offline` air-gapped cache) | `qwsec --offline src/server.py "Check for injection"` |
| `qwpipe` | — | Piped stream processor for shell stdout/stderr | `git diff \| qwpipe "Review changes for breaking bugs"` |
| `qwcli` | `qwc` | Interactive terminal chat or single-turn query (`-s`) | `qwcli -c 32 -r 2` |
| `qws` | — | Single-turn query shortcut (unquoted prompts supported) | `qws explain Kalman filter sensor fusion in robotics` |
| `qwsearch` | `qwsr` | Tor-isolated web search with local Qwen synthesis (`--chaff` traffic entropy) | `qwsearch --chaff -r 3 "Linux 6.13 scheduler"` |
| `qwdoctor` | `qw check` | Diagnostic environment health check and OPSEC verification | `qwdoctor` / `qw check` |
| `qwserver` | `qw` | Launches `llama-server` with custom context, port, and reasoning | `qwserver -c 32 -p 61232 -r 2` |
| `qstop` | — | Terminates active `llama-server` and `llama-cli` processes | `qstop` |
| `cll` | — | Unified CLI and multi-model runner (status, logs, model, server, chat) | `cll status` / `cll server` |

---

### Terminal Command Reference Guide

#### 1. Codebase & File Analyzer (`qwfile`)

`qwfile` is a unified code and document analysis engine capable of analyzing single files, remote links, and whole multi-thousand-file repositories.

```bash
qwfile [-c 16|32|48] [-r 0..4] [-f pdf|txt|code] [--web] [--keep] [--export <dir>] <target> [prompt...]
```

- **Smart Path & Alias Resolution:** Automatically resolves relative paths, `~` tilde paths, fuzzy project names (e.g. `my-project` resolved under `~/Projects/` or `~/Code/`), and local subdirectories.
- **In-Memory Dependency Symbol Resolver (RAM Cache):** When inspecting a C/C++ or Python file, `qwfile` scans `#include` and `import` statements, statically extracts class, struct, enum, and function signatures into RAM cache in < 10 ms, filters down to only the symbols actually referenced in the target file, and injects them into the prompt.
- **Anonymous Dependency Research (`--web` / `--search`) & `.qwignore`:** Scans project manifests (`requirements.txt`, `package.json`, `Cargo.toml`, etc.), extracts public package names, and queries Tor SOCKS5h (`127.0.0.1:9050`) for live security advisories without ever leaking project code. Proprietary libraries (`pkg:corp-*`) and sensitive paths (`secrets/`) are automatically masked via `.qwignore` (see `.qwignore.example`, [OPSEC Guide](file:///home/sups/Local-LLM-Unsensored/guide/opsec_codebase_search.md) and [Anonymous Research Guide](file:///home/sups/Local-LLM-Unsensored/guide/anonymous_research_guide.md)).
- **Remote Repositories & URLs over Tor:** Supports GitHub repository shorthand (`owner/repo` or `owner/repo/path/to/file`) and raw web URLs, downloading and analyzing text strictly through Tor SOCKS5h (`127.0.0.1:9050`).
- **Hierarchical Project & Directory Explorer:** When `<target>` is a directory or repository (e.g. `qwfile my-project` or `qwfile .`):
  1. **Tree Exploration (`ls`):** Maps the directory structure, filtering out `.git`, `__pycache__`, `.venv`, and binary artifacts.
  2. **Chunked Module Analysis:** Partitions the repository into manageable subsystem chunks (up to 24,000 characters each) and analyzes each module sequentially.
  3. **Note Taking in `/tmp/local-llm/`:** Saves intermediate module notes to `/tmp/local-llm/<project>/notes/module_XX.md`, directory maps to `00_tree.txt`, and architecture notes to `01_overview.md`.
  4. **Consolidated Final Synthesis:** Synthesizes accumulated notes into a final report streamed live to stdout and saved to `/tmp/local-llm/<project>/final_analysis.md`.
- **Options & Flags:**
  - `-c 16|32|48`: Context tokens (16K, 32K [default], 48K max ceiling).
  - `-r 0..4`: Reasoning effort (0: `off`, 1: `low`, 2: `medium` [default], 3: `high`, 4: `max`).
  - `-f pdf|txt|code`: Format override (PDF files are extracted via `pdftotext`).
  - `--web`: Enables Tor-isolated web research on detected package dependencies.
  - `--keep`: Copies the complete notes and report from `/tmp/` to permanent storage under `~/.local/share/local-llm/reports/<project>_<timestamp>/`.
  - `--export <dir>`: Exports the complete analysis workspace to a custom directory.

##### Examples:
```bash
# Analyze a single header with automatic dependency symbol resolution
qwfile src/core/engine.h "Explain state management and concurrency controls"

# Analyze a whole repository with hierarchical chunking and live streaming
qwfile my-project "Analyze overall architecture, data pipeline, and error handling"

# Hybrid audit: inspect repository and search Tor anonymously for modern library best practices
qwfile --web -c 32 src/ "Audit architecture and recommend dependency upgrades"

# Analyze a remote GitHub repository over Tor with high reasoning
qwfile torproject/tor -r 3 "Describe connection handshake and hidden service directory architecture"

# Analyze and permanently archive notes
qwfile src/ --keep "Audit memory safety and concurrency risks"
```

---

#### 2. Security Auditor & Vulnerability Scanner (`qwsec`)

`qwsec` runs deep vulnerability inspections against OWASP Top 10, CWE, memory safety issues, injection, broken crypto, authentication flaws, and logic bugs.

```bash
qwsec [-c 16|32|48] [-r 0..4] [--web] [--offline] <file_or_code> [prompt...]
```

- Accepts a file path, a raw code string, or piped code from stdin.
- Automatically applies `prompts/cli_rules.md` security personas.
- `--web`: Anonymously checks Tor SOCKS5h for known CVEs affecting imported packages.
- `--offline`: Zero-network air-gapped vulnerability audit using the local CVE advisory cache.
- Identifies vulnerability severity, explains exploit vectors, and outputs hardened refactored code.

##### Examples:
```bash
# Audit a Python backend server with live Tor dependency research
qwsec --web cll/server.py "Check for CSRF, SSRF, and unauthenticated endpoints"

# Air-gapped offline security audit (zero network packets emitted)
qwsec --offline src/driver.c "Check for buffer overflows and race conditions"

# Pipe code directly from git diff or clipboard
git show HEAD | qwsec "Audit commit for security regressions"
```

---

#### 3. Piped Stream Processor (`qwpipe`)

`qwpipe` processes arbitrary command output streamed through stdin without saving intermediate files:

```bash
<command> | qwpipe [-c 16|32|48] [-r 0..4] [prompt...]
```

- Bypasses Linux kernel argument length limits using temporary file streaming.
- Ideal for analyzing build failures, compiler errors, systemd journal logs, and network outputs.

##### Examples:
```bash
# Diagnose a build or compiler error
cargo build 2>&1 | qwpipe -c 32 "Explain the compilation error and provide the fix"

# Analyze system logs
journalctl -u tor -n 100 --no-pager | qwpipe "Identify circuit failure reasons"
```

---

#### 4. Interactive & Single-Turn Terminal Chat (`qwcli` / `qws`)

```bash
qwcli [-c 16|32|48] [-r 0..4] [-s] [-p "prompt"] [--rules|--no-rules]
qws [prompt...]
```

- **Interactive Mode (`qwcli`):** Starts a multi-turn conversation in the terminal.
- **Single-Turn Mode (`qwcli -s` or `qws`):** Answers the question directly and exits cleanly.
- **Unquoted Prompt Support:** `qws` accepts multi-word prompts without requiring enclosing quotes.
- **Rules Toggle:** `--rules` enforces direct developer guidelines (`prompts/cli_rules.md`); `--no-rules` allows raw model generation.

##### Examples:
```bash
# Start interactive terminal session
qwcli -c 32 -r 2

# Instant single-turn query without quotes
qws explain how EKF handles IMU gyro drift and GPS loss

# Query with maximum reasoning effort
qwcli -r 4 -s -p "Prove that the square root of 2 is irrational"
```

---

#### 5. Tor-Isolated Web Search (`qwsearch`)

`qwsearch` queries external search engines and `.onion` hidden services strictly over Tor SOCKS5h (`127.0.0.1:9050`):

```bash
qwsearch [-r 0..4] [-n limit] [--raw] [--json] [--leak-test] [--new-circuit] [--chaff] <query>
```

- **Strict Fail-Closed OPSEC:** Aborts immediately if Tor is offline. Uses `socks5h://` so all DNS resolution occurs on the Tor exit node.
- **Traffic Analysis Resistance (`--chaff` / `--decoy`):** Emits randomized decoy queries with jitter delays to defeat timing and query correlation at Tor exit nodes.
- **Multi-Engine Cascade:** Queries DuckDuckGo HTML, Bing (Tor), Wikipedia REST API, and GitHub Search API.
- **Native `.onion` Discovery:** Automatically queries Ahmia hidden service search for `.onion` and dark web queries.

##### Examples:
```bash
# Web search with Qwen synthesis
qwsearch "Arch Linux latest package updates"

# Search with decoy traffic against exit node timing analysis
qwsearch --chaff "Linux 6.13 scheduler changes"

# High reasoning search on technical protocol
qwsearch -r 3 "Ed25519 signature malleability vulnerabilities"

# Raw markdown output piped into security audit
qwsearch --raw "OpenSSL CVE 2026" | qwsec "Evaluate impact on our system"

# Verify Tor circuit and check exit IP
qwsearch --leak-test
```

---

#### 6. Server Control (`qwserver` / `qstop`)

```bash
qwserver [-c 16|32|48] [-p port] [-r 0..4]
qstop
```

- `qwserver`: Launches `llama-server` on `127.0.0.1:61232` (or custom `-p`) with Flash Attention, Q4_0 KV cache, and 512 MiB VRAM safety margin.
- `qstop`: Safely terminates any running `llama-server` or `llama-cli` processes and releases GPU memory.

---

#### 7. Chat Local LLM CLI & Multi-Model Runner (`cll`)

`cll` is the unified command-line entry point for running, managing, and inspecting models, backends, and privacy tools:

```bash
cll server                         # Start background server with active model
cll chat                           # Interactive terminal chat with active model
cll -m qwen2.5-coder-3b chat       # Chat with Qwen2.5-Coder without changing default
cll status                         # Check active processes, gateway ports, and VRAM
cll logs -f                        # Follow live gateway & reaper journalctl logs
cll model list                     # List registered models and download status
cll model use qwen2.5-coder-3b     # Switch persistent default model
cll model pull qwen2.5-coder-3b    # Download model weights from HuggingFace
cll search "query"                 # Run anonymous Tor web & onion search
cll stop                           # Safely terminate all active server & bridge processes
```

- **Per-Command Model Overrides:** Any command can take `-m <id>` or `--model <id>` to evaluate an alternate model without rewriting configuration.
- **Service & Resource Inspection:** `cll status` reports active model metadata, gateway port bindings (`61230`–`61232`), process IDs, and real-time GPU VRAM allocation.
- **Log Streaming:** `cll logs` inspects systemd journal logs from `cll-reaper.service`.
- **Zero Disk Leakage:** All server runs enforce `--log-disable` and strict Tor-only outbound traffic.

---

#### 8. System Health & OPSEC Diagnostics (`qwdoctor` / `qw check`)

`qwdoctor` (shorthand `qw check`) runs an automated diagnostic audit across all suite components:

```bash
qwdoctor
qw check
qwdoctor --json
```

- Verifies Tor SOCKS5h port `9050` connectivity.
- Performs Tor exit IP leak check against `check.torproject.org`.
- Checks `llama-server` process status and port `61232` health (and `cll-reaper` on port `61230`).
- Scans and validates local GGUF model files.
- Checks `cll` port `41625` binding and UI assets.
- Verifies `.qwignore` active pattern counts and syntax.
- Checks Python environment and critical dependencies.

---

#### 9. Manual Pages (`man 1`)

Standard UNIX manual pages are provided under `man/man1/` and automatically linked to `~/.local/share/man/man1` by `setup.sh`:

```bash
man qwfile
```

```bash
man qwsec
```

```bash
man qwpipe
```

```bash
man qwcli
```

```bash
man qwserver
```

```bash
man qwdoctor
```

| Manual Page | Description |
| :--- | :--- |
| `man qwfile` | Complete manual for file, remote URL, and hierarchical codebase analyzer, including symbol resolving and chunking options |
| `man qwsec` | Security audit manual covering vulnerability analysis profiles and piped usage |
| `man qwpipe` | Piped standard input processing manual |
| `man qwcli` | Interactive and single-turn terminal LLM client manual |
| `man qwserver` | High-throughput `llama-server` background daemon manual |

### D. Direct Hugging Face Execution (Without Pre-downloading)

Interactive terminal session:

```bash
llama-cli -hf mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-i1-GGUF -hff Huihui-Qwen3-4B-Instruct-2507-abliterated.i1-Q4_K_M.gguf -ngl auto -fit on -fitt 512 -c 32768 -fa on -ctk q4_0 -ctv q4_0 -t 6
```

Local API server:

```bash
llama-server -hf Qwen/Qwen2.5-Coder-3B-Instruct-GGUF -hff qwen2.5-coder-3b-instruct-q4_k_m.gguf -ngl auto -fit on -fitt 512 -c 32768 -np 1 -fa on -ctk q4_0 -ctv q4_0 -t 6 --port 61232
```

### E. OpenCode Autonomous Coding Agent Integration

The suite includes native, turnkey compatibility with the [OpenCode](https://opencode.ai) autonomous coding agent CLI and desktop interface via `cll.opencode_bridge` and `cll-reaper`.

#### Architecture & Capabilities

```
+-------------------------------------------------------------+
|                     OpenCode CLI / TUI                      |
+-------------------------------------------------------------+
                              | HTTP (Port 61230 + Bearer Auth)
                              v
+-------------------------------------------------------------+
|                        cll-reaper                           |
|  - Minimal (2.4 MB RSS) Rust watchdog & auth gateway        |
|  - Verifies local Authorization token (drops 401 unauth)   |
|  - Lazy on-demand auto-starter for backend (~2.5s)          |
|  - 15-minute idle VRAM reaper (triggers qstop)              |
+-------------------------------------------------------------+
                              | HTTP (Port 61231)
                              v
+-------------------------------------------------------------+
|                   cll.opencode_bridge                       |
|  - Prunes # Code Mode & unused cloud skill catalogs         |
|  - Injects Senior Systems Architect directives              |
|  - Injects autonomous Tor search tool (tor_search)          |
|  - Translates tor_search -> shell (torsearch ...)           |
|  - Recovers raw JSON tool calls emitted without XML tags    |
|  - Maps reasoning effort ('low', 'medium', 'high')          |
|  - Retries connection while llama-server allocates CUDA     |
+-------------------------------------------------------------+
                              | HTTP (Port 61232)
                              v
+-------------------------------------------------------------+
|                  llama-server (Qwen3-4B)                    |
+-------------------------------------------------------------+
```

1. **Automatic Gateway Startup:** Running `cll-reaper` as a user service (`cll-reaper.service`) or standalone process listens on `127.0.0.1:61230`. OpenCode requests automatically launch the backend on ports `61231` (bridge) and `61232` (llama-server) without pre-allocating GPU memory.
2. **Local Authorization Protection:** Protects against unauthorized local loopback requests (CSRF, DNS rebinding, or stray scripts). Requests lacking `Authorization: Bearer <token>` are dropped with `401 Unauthorized` without waking the model or consuming VRAM.
3. **Context Preservation:** Strips unnecessary cloud agent prompts, unused desktop skills, and container boilerplate, freeing up ~2,000 tokens of context.
4. **Autonomous Tor Web Search:** The agent is empowered with real-time web, GitHub, ArXiv, and `.onion` dark web search routed 100% over Tor SOCKS5h. Tool calls to `tor_search` are automatically rewritten into local `torsearch` shell calls with prompt injection defenses.
5. **Resilient Tool Parsing:** Recovers raw JSON function calls when the model emits valid tool calls without explicit `<tool_call>` XML wrappers.

#### Configuration (`opencode.json`)

The repository includes a ready-to-use `opencode.json` configuring the local provider, permissions, and tool access:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "update": "disable",
  "websearch": false,
  "experimental": {
    "image_generate": false
  },
  "policies": [
    { "action": "tool.use", "resource": "execute", "effect": "deny" },
    { "action": "tool.use", "resource": "webfetch", "effect": "deny" },
    { "action": "tool.use", "resource": "skill", "effect": "deny" },
    { "action": "skill.use", "resource": "*", "effect": "deny" }
  ],
  "permissions": [
    { "action": "shell", "resource": "torsearch*", "effect": "allow" },
    { "action": "shell", "resource": "qwsearch*", "effect": "allow" },
    { "action": "shell", "resource": "qwsr*", "effect": "allow" }
  ],
  "providers": {
    "local-cll": {
      "name": "Local CLL (Qwen3-4B)",
      "package": "@ai-sdk/openai-compatible",
      "settings": {
        "baseURL": "http://127.0.0.1:61230/v1",
        "apiKey": "cll-local-sec-98f2b"
      },
      "models": {
        "qwen3-4b": {
          "name": "Qwen3-4B Unsensored",
          "limit": {
            "context": 32768,
            "output": 8192
          },
          "capabilities": {
            "tools": true,
            "temperature": true,
            "reasoning": {
              "supported": true,
              "effort": ["low", "medium", "high"]
            }
          },
          "variants": [
            { "id": "low", "body": { "reasoning_effort": "low" } },
            { "id": "medium", "body": { "reasoning_effort": "medium" } },
            { "id": "high", "body": { "reasoning_effort": "high" } }
          ]
        }
      }
    }
  },
  "model": "local-cll/qwen3-4b#medium"
}
```

#### Running OpenCode with Local Qwen3-4B

In your terminal or project directory, simply launch OpenCode:

```bash
opencode run "Audit memory safety and concurrency risks in src/driver.c"
```

```bash
opencode
```

#### On-Demand Lazy Auto-Start & Idle Reaper (`cll-reaper`)

Rather than leaving `llama-server` holding 2.8 GB VRAM all day or manually managing server lifecycles, run the minimal (2.4 MB RAM) Rust watchdog daemon:

```bash
cll-reaper
```

Or enable it as a systemd user service:

```bash
systemctl --user enable --now cll-reaper.service
```

- **Listening Port:** `127.0.0.1:61230` (standard OpenCode target).
- **Auto-Start:** When OpenCode dispatches a prompt, `cll-reaper` detects if the backend is down and spawns it in the background in ~2.5 seconds.
- **Idle Reaper:** When no requests arrive for `LLM_IDLE_TIMEOUT` seconds (default: 900s / 15 minutes), `cll-reaper` automatically executes `qstop`, completely releasing GPU memory.
- **Configurable Environment Variables:**
  - `REAPER_BIND`: External listen socket (default: `127.0.0.1:61230`).
  - `BACKEND_TARGET`: Internal bridge forwarding address (default: `127.0.0.1:61231`).
  - `LLAMA_TARGET`: Core LLM server address (default: `127.0.0.1:61232`).
  - `REAPER_API_KEY`: Local authorization token (default: `cll-local-sec-98f2b`).
  - `LLM_IDLE_TIMEOUT`: Inactivity timeout in seconds (default: `900`, `0` to disable auto-shutdown).

### F. Docker Execution (Optional)

```bash
docker run --gpus all --rm -it -p 61232:61232 -v "$(pwd):/models" ghcr.io/ggml-org/llama.cpp:server-cuda -m /models/qwen2.5-coder-3b-instruct-q4_k_m.gguf -ngl auto -c 32768 -fa on -ctk q4_0 -ctv q4_0 --host 0.0.0.0 --port 61232
```

---

## 6. Default Runtime Parameters

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `-ngl` | `auto` | Automatically offloads the maximum number of layers that fit into free VRAM (37 offloadable layers in Qwen3-4B). |
| `-fit on -fitt 512` | `512` MiB | Reserves a 512 MiB VRAM safety margin to avoid `cudaMalloc` out-of-memory errors. |
| `-c` | `32768` | Context window size in tokens (32K default, configurable up to 49,152 / 48K). |
| `-np` | `1` | Allocates a single parallel slot on `llama-server` to prevent 4x KV cache allocation. |
| `-fa on` | `on` | Enables Flash Attention (`llama.cpp` >= 0.6 requires explicit `on`, `off`, or `auto`). |
| `-ctk q4_0 -ctv q4_0` | `q4_0` | Quantizes K and V caches to 4-bit, enabling 32K–48K context windows within 4 GB VRAM. |
| `-t` | `6` | Number of CPU threads allocated for non-offloaded layers (tuned for 6 physical cores). |
