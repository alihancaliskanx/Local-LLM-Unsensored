# Local LLM Uncensored (Abliterated) Inference Setup

Local inference configuration and runner scripts for abliterated (uncensored) models using `llama.cpp` on Arch Linux / CachyOS, tuned for 4 GB VRAM + 16 GB RAM. The default model is `Huihui-Qwen3-4B-Instruct-2507-abliterated` (`Q4_K_M`, ~2.5 GB).

---

## 1. Overview of Abliterated Models

Abliterated models remove the refusal direction from the base model's weight matrices via orthogonalization without requiring full fine-tuning. This disables refusal filters while preserving the model's original coding, reasoning, and tool-calling capabilities.

### Model Selection by Hardware Tier

| Hardware Tier | Model | GGUF Repository | Quantization | Status |
| :--- | :--- | :--- | :--- | :--- |
| **4 GB VRAM + 16 GB RAM** | `Huihui-Qwen3-4B-Instruct-2507-abliterated` | `mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-i1-GGUF` | `i1-Q4_K_M` (~2.5 GB) | Default, benchmarked below |
| **6–8 GB VRAM** | `Huihui-Qwen3-8B-abliterated-v2` | `mradermacher/Huihui-Qwen3-8B-abliterated-v2-GGUF` | `Q4_K_M` (~5.0 GB) | Not tested |
| **16 GB+ VRAM or 32 GB RAM (MoE)** | `Huihui-Qwen3-30B-A3B-Instruct-2507-abliterated` | `mradermacher/Huihui-Qwen3-30B-A3B-Instruct-2507-abliterated-i1-GGUF` | `i1-Q4_K_M` (~18.6 GB) | Not tested |

Use any other model with `MODEL_PATH=/path/to/model.gguf qwen-local server`.

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
| `setup.sh` | One-time setup: installs `llama.cpp`, downloads the model, and links the `qwen-local` command into `~/.local/bin` |
| `qwen-local` | Command entry point: dispatches `qwen-local server` and `qwen-local cli` to `scripts/` |
| `qwen.zsh` | Shell entry point sourcing modular helper scripts under `shell/` |
| `shell/core.zsh` | Shared context/reasoning resolvers (`32K` default, `48K` ceiling) and `qstop` |
| `shell/cli.zsh` | Terminal functions (`qwserver`, `qwcli`, `qwfile`, `qwsec`, `qwpipe`) using `-f` file input to bypass the 128 KiB kernel argument limit |
| `shell/web.zsh` | Tor web search (`qwsearch`) and Chat Local LLM (`cll`) launchers |
| `scripts/common.sh` | Shared runtime defaults (`CTX=32768`, `-ctk q4_0 -ctv q4_0`) and GPU/binary checks |
| `scripts/run-server.sh` | Launches `llama-server` on `127.0.0.1:8080` |
| `scripts/run-cli.sh` | Launches interactive or single-turn chat via `llama-cli` (loads `prompts/cli_rules.md`) |
| `scripts/pre-commit` | Git pre-commit hook scanning diffs for secrets and security flaws via active server or CLI |
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
3. Links the `qwen-local` command into `~/.local/bin` (or `BIN_DIR`). An existing `qwen-local` that points elsewhere is never overwritten.

Remove the `qwen-local` link again with `./setup.sh --uninstall`; installed packages and the model are kept.

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

After `setup.sh`, `qwen-local` works from any directory. Without it, `./run-server.sh` and `./run-cli.sh` take the same arguments and environment variables. Options after the command are passed to `llama.cpp` unchanged.

### A. Local Web UI and OpenAI API Server

```bash
qwen-local server
```

- **Web UI:** `http://127.0.0.1:8080`
- **OpenAI API Endpoint:** `http://127.0.0.1:8080/v1`

Override runtime parameters with environment variables when needed:

```bash
NGL=20 CTX=4096 PORT=8080 qwen-local server
```

### B. Interactive Terminal Chat

```bash
qwen-local cli
```

If a custom `rules.md` file exists in the repository root (or is pointed to via `RULES_PATH`), `qwen-local cli` automatically injects it as the system prompt using `-sysf`.

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
| `qwsec` | — | Security audit and CWE/OWASP vulnerability scanner | `qwsec cll/server.py "Check for CSRF and injection"` |
| `qwpipe` | — | Piped stream processor for shell stdout/stderr | `git diff \| qwpipe "Review changes for breaking bugs"` |
| `qwcli` | `qwc` | Interactive terminal chat or single-turn query (`-s`) | `qwcli -c 32 -r 2` |
| `qws` | — | Single-turn query shortcut (unquoted prompts supported) | `qws explain Kalman filter sensor fusion in robotics` |
| `qwsearch` | `qwsr` | Tor-isolated web search with local Qwen synthesis | `qwsearch -r 3 "Linux 6.13 scheduler changes"` |
| `qwserver` | `qw` | Launches `llama-server` with custom context, port, and reasoning | `qwserver -c 32 -p 8080 -r 2` |
| `qstop` | — | Terminates active `llama-server` and `llama-cli` processes | `qstop` |
| `cll` | — | Launches Chat Local LLM Web UI (`127.0.0.1:41625`) | `cll` / `cll stop` |

---

### Terminal Command Reference Guide

#### 1. Codebase & File Analyzer (`qwfile`)

`qwfile` is a unified code and document analysis engine capable of analyzing single files, remote links, and whole multi-thousand-file repositories.

```bash
qwfile [-c 16|32|48] [-r 0..4] [-f pdf|txt|code] [--keep] [--export <dir>] <target> [prompt...]
```

- **Smart Path & Alias Resolution:** Automatically resolves relative paths, `~` tilde paths, fuzzy project names (e.g. `my-project` resolved under `~/Projects/` or `~/Code/`), and local subdirectories.
- **In-Memory Dependency Symbol Resolver (RAM Cache):** When inspecting a C/C++ or Python file, `qwfile` scans `#include` and `import` statements, statically extracts class, struct, enum, and function signatures into RAM cache in < 10 ms, filters down to only the symbols actually referenced in the target file, and injects them into the prompt.
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
  - `--keep`: Copies the complete notes and report from `/tmp/` to permanent storage under `~/.local/share/local-llm/reports/<project>_<timestamp>/`.
  - `--export <dir>`: Exports the complete analysis workspace to a custom directory.

##### Examples:
```bash
# Analyze a single header with automatic dependency symbol resolution
qwfile src/core/engine.h "Explain state management and concurrency controls"

# Analyze a whole repository with hierarchical chunking and live streaming
qwfile my-project "Analyze overall architecture, data pipeline, and error handling"

# Analyze a remote GitHub repository over Tor with high reasoning
qwfile torproject/tor -r 3 "Describe connection handshake and hidden service directory architecture"

# Analyze and permanently archive notes
qwfile src/ --keep "Audit memory safety and concurrency risks"
```

---

#### 2. Security Auditor & Vulnerability Scanner (`qwsec`)

`qwsec` runs deep vulnerability inspections against OWASP Top 10, CWE, memory safety issues, injection, broken crypto, authentication flaws, and logic bugs.

```bash
qwsec [-c 16|32|48] [-r 0..4] <file_or_code> [prompt...]
```

- Accepts a file path, a raw code string, or piped code from stdin.
- Automatically applies `prompts/cli_rules.md` security personas.
- Identifies vulnerability severity, explains exploit vectors, and outputs hardened refactored code.

##### Examples:
```bash
# Audit a Python backend server
qwsec cll/server.py "Check for CSRF, SSRF, and unauthenticated endpoints"

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
qwsearch [-r 0..4] [-n limit] [--raw] [--json] [--leak-test] [--new-circuit] <query>
```

- **Strict Fail-Closed OPSEC:** Aborts immediately if Tor is offline. Uses `socks5h://` so all DNS resolution occurs on the Tor exit node.
- **Multi-Engine Cascade:** Queries DuckDuckGo HTML, Bing (Tor), Wikipedia REST API, and GitHub Search API.
- **Native `.onion` Discovery:** Automatically queries Ahmia hidden service search for `.onion` and dark web queries.

##### Examples:
```bash
# Web search with Qwen synthesis
qwsearch "Arch Linux latest package updates"

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

- `qwserver`: Launches `llama-server` on `127.0.0.1:8080` (or custom `-p`) with Flash Attention, Q4_0 KV cache, and 512 MiB VRAM safety margin.
- `qstop`: Safely terminates any running `llama-server` or `llama-cli` processes and releases GPU memory.

---

#### 7. Chat Local LLM Web Gateway (`cll`)

`cll` launches the full-featured browser interface on `http://127.0.0.1:41625` with integrated Tor controls and LLM power management:

```bash
cll
cll stop
```

- Embeds upstream `llama-ui` frontend.
- Live token limit selector (4K to 48K context).
- Live Tor IP rotation (`🔄 New IP`) and complete browser history wiper.
- Zero disk logging (`--log-disable`).

---

#### 8. Manual Pages (`man 1`)

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
llama-server -hf mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-i1-GGUF -hff Huihui-Qwen3-4B-Instruct-2507-abliterated.i1-Q4_K_M.gguf -ngl auto -fit on -fitt 512 -c 32768 -np 1 -fa on -ctk q4_0 -ctv q4_0 -t 6 --port 8080
```

### E. Docker Execution (Optional)

```bash
docker run --gpus all --rm -it -p 8080:8080 -v "$(pwd):/models" ghcr.io/ggml-org/llama.cpp:server-cuda -m /models/Huihui-Qwen3-4B-Instruct-2507-abliterated.i1-Q4_K_M.gguf -ngl 28 -c 32768 -fa on -ctk q4_0 -ctv q4_0 --host 0.0.0.0 --port 8080
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
