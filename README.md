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

| File | Description |
| :--- | :--- |
| `setup.sh` | One-time setup: installs `llama.cpp`, downloads the model, and links the `qwen-local` command into `~/.local/bin` |
| `qwen-local` | Command entry point: `qwen-local server` and `qwen-local cli` |
| `qwen.zsh` | Shell helper functions (`qwcli`, `qwfile`, `qwpipe`, `qwsearch`, `qwserver`, `qstop`) with context multipliers and reasoning controls |
| `qwsearch.py` | Privacy-preserving, Tor-only web search synthesis engine with strict Fail-Closed OPSEC |
| `qwen-web.py` | Local web agent server with Auto-Detect routing, streaming UI, and Prompt Injection Shield |
| `page_reader.py` | Safe, Tor-only webpage and `.onion` text extractor with script/style stripping |
| `security_guard.py` | Multi-layer prompt injection defense and strict XML untrusted-data sandboxing |
| `rules.md` | System prompt rules configuring the model for direct developer assistant responses |
| `run-server.sh` | Launches `llama-server` with Web UI and OpenAI-compatible API (`127.0.0.1:8080`) |
| `run-cli.sh` | Launches interactive terminal chat via `llama-cli` (loads `rules.md` via `-sysf` if present) |
| `common.sh` | Shared runtime defaults and startup checks sourced by both launchers |
| `.gitignore` | Excludes large `*.gguf` model weights, partial downloads, and runtime logs from version control |

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

The shell integration provides commands with automatic context scaling, reasoning effort control, and output filtering:

| Command | Description | Example |
| :--- | :--- | :--- |
| `qwcli` (`qwc`) | Terminal chat or single-turn query (`-s`) | `qwcli -c 16 -r 2 -s -p "Explain recursion"` |
| `qws` | Short alias for single-turn query (`qwcli -s -p`) | `qws "What is Rayleigh scattering?"` |
| `qwsearch` (`qwsr`) | Tor-isolated web search with local Qwen synthesis | `qwsearch "Arch Linux latest changes"` |
| `qwfile` | Document & code analyzer (supports `.pdf`, `.txt`, code) | `qwfile -c 32 -r 3 qwen-local "Analyze this script"` |
| `qwpipe` | Pipe processor for shell stdout/stderr | `cat build.log \| qwpipe -c 16 "Find root cause"` |
| `qwserver` (`qw`) | Launches server with context, port, and reasoning | `qwserver -c 16 -p 8080 -r 2` |
| `qstop` | Terminates running `llama-server` and `llama-cli` processes | `qstop` |

#### Common Flags

- `-c <num>`: Context tokens. Multipliers <= 256 are multiplied by 1024 (e.g., `-c 16` -> 16,384 tokens, `-c 32` -> 32,768 tokens; model ceiling: 32,768). Default: `16`.
- `-r <0..4>`: Reasoning effort (0: `off`, 1: `low`, 2: `medium` [default], 3: `high`, 4: `max`).
- `-R`, `--no-rules`: Disables `rules.md` (raw model behavior). Default for single-turn queries.
- `--rules`: Forces developer rules on single-turn queries. Default for interactive terminal chat.
- `-f <format>`: (`qwfile` only) Force parser format: `pdf`, `txt`, or `code`. Automatic by default (requires `poppler`'s `pdftotext` for PDF).
- `-h`, `--help`: Displays command usage.

#### Tor-Isolated Web Search (`qwsearch`)

`qwsearch` allows local models to answer queries using real-time internet data while maintaining an absolute OPSEC guarantee: **no packets or DNS queries ever leave the machine outside the Tor network**.

- **Fail-Closed Gatekeeper:** Probes `127.0.0.1:9050` before every request. If Tor is stopped or unreachable, the process aborts immediately (exit code 2) without attempting cleartext connections.
- **Remote DNS Resolution:** Uses `socks5h://` so domain names are resolved exclusively by the Tor exit node, preventing local ISP DNS leakage.
- **Resilient Engine Cascade:** Tries DuckDuckGo HTML first; if blocked by anti-bot rate limits on the Tor circuit, automatically falls back to Bing over Tor SOCKS5h, enriched with Wikipedia context.
- **Useful Flags:**
  - `qwsearch "query"`: Standard search and synthesis.
  - `qwsearch --raw "query"`: Outputs Markdown search context without running the LLM (ideal for piping into `qwpipe`).
  - `qwsearch --json "query"`: Outputs raw search results as JSON.
  - `qwsearch --leak-test`: Audits the Tor connection via `check.torproject.org` and prints the active exit node IP.
  - `qwsearch --new-circuit "query"`: Requests a fresh Tor identity (SIGNAL NEWNYM) before querying.

> [!NOTE]
> The built-in `llama-server` Web UI (`http://127.0.0.1:8080`) is a static offline C++ interface without tool-calling hooks. Real-time Tor web search is driven through `qwsearch` in the CLI or through the shielded `qwweb` interface.

#### Chat Local LLM (`cll`) — Authentic llama-ui with Tor & Power Bar

`cll` launches the gateway on `http://127.0.0.1:41625` and opens your default browser automatically:

```bash
cll
```

- **Authentic `llama-ui` Frontend:** Embeds the full upstream `llama-ui` interface (chat branching, message editing, file/document attachments, sampling parameters, token counters).
- **Integrated Control Bar:** Manage LLM power state (On/Off), Token Limit (4K to 32K context), Reasoning levels (0..4), and Tor Web / `.onion` search modes directly from the page without popups.
- **Strict Zero-Log Privacy:** `llama-server` is spawned with `--log-disable` and all process I/O is directed to `/dev/null`.
- **Tor OPSEC & .onion Discovery:** Searches Ahmia for `.onion` queries, handles parallel scraping, and protects against prompt injection.
- **Clear All History:** Includes an instant storage wipe button that deletes local origin data and IndexedDB databases.

To stop the server:
```bash
cll stop
```

### D. Direct Hugging Face Execution (Without Pre-downloading)

Interactive terminal session:

```bash
llama-cli -hf mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-i1-GGUF -hff Huihui-Qwen3-4B-Instruct-2507-abliterated.i1-Q4_K_M.gguf -ngl auto -fit on -fitt 512 -c 8192 -fa on -ctk q8_0 -ctv q8_0 -t 6
```

Local API server:

```bash
llama-server -hf mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-i1-GGUF -hff Huihui-Qwen3-4B-Instruct-2507-abliterated.i1-Q4_K_M.gguf -ngl auto -fit on -fitt 512 -c 8192 -np 1 -fa on -ctk q8_0 -ctv q8_0 -t 6 --port 8080
```

### E. Docker Execution (Optional)

```bash
docker run --gpus all --rm -it -p 8080:8080 -v "$(pwd):/models" ghcr.io/ggml-org/llama.cpp:server-cuda -m /models/Huihui-Qwen3-4B-Instruct-2507-abliterated.i1-Q4_K_M.gguf -ngl 28 -c 8192 -fa on -ctk q8_0 -ctv q8_0 --host 0.0.0.0 --port 8080
```

---

## 6. Default Runtime Parameters

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `-ngl` | `auto` | Automatically offloads the maximum number of layers that fit into free VRAM (37 offloadable layers in Qwen3-4B). |
| `-fit on -fitt 512` | `512` MiB | Reserves a 512 MiB VRAM safety margin to avoid `cudaMalloc` out-of-memory errors. |
| `-c` | `8192` | Context window size in tokens. |
| `-np` | `1` | Allocates a single parallel slot on `llama-server` to prevent 4x KV cache allocation. |
| `-fa on` | `on` | Enables Flash Attention (`llama.cpp` >= 0.6 requires explicit `on`, `off`, or `auto`). |
| `-ctk q8_0 -ctv q8_0` | `q8_0` | Quantizes K and V caches to 8-bit, halving the KV cache from ~1.2 GB to ~600 MB on 8192 context. |
| `-t` | `6` | Number of CPU threads allocated for non-offloaded layers (tuned for 6 physical cores). |
