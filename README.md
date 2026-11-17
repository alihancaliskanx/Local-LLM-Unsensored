# Chat Local LLM (CLL)

**A high-performance, privacy-first local LLM inference platform with lazy GPU lifecycle management, autonomous Tor research, and multi-model registry.**

Optimized for constrained hardware (4 GB VRAM + 16 GB RAM) and production developer workflows on Arch Linux / CachyOS.

---

## Key Highlights

- **Multi-Model Registry:** Seamlessly switch between official aligned coding models (`Qwen2.5-Coder-3B`), reasoning distillations (`DeepSeek-R1-1.5B`), and unrestricted/abliterated models (`Qwen3-4B`).
- **4 GB VRAM Zero-OOM Engine:** Native `llama.cpp` integration with Flash Attention and 4-bit KV cache quantization (`q4_0`), enabling full 32K context windows on entry-level GPUs at 60–75 tok/s.
- **On-Demand GPU Reaper (`cll-reaper`):** 2.4 MB Rust daemon listening on `127.0.0.1:61230` with Bearer authentication. Auto-spawns backends in ~2.5s on incoming requests and executes `qstop` after 15 minutes of inactivity, releasing GPU VRAM to 0 MiB.
- **Autonomous Tor Research (`torsearch`):** Fail-Closed SOCKS5h (`127.0.0.1:9050`) search and scraping engine. Zero clearnet leaks, DNS query masking, and dark web (`.onion`) discovery.
- **Turnkey OpenCode Integration:** Drop-in OpenAI-compatible gateway (`cll.opencode_bridge`) that prunes cloud bloat, injects systems directives, and translates autonomous tool calls to Tor search.

---

## Table of Contents

1. [Quickstart](#1-quickstart)
2. [Unified CLI (`cll`)](#2-unified-cli-cll)
3. [Multi-Model Profiles & Hardware Alignment](#3-multi-model-profiles--hardware-alignment)
4. [Autonomous Coding Agent Integration (OpenCode)](#4-autonomous-coding-agent-integration-opencode)
5. [Tor Privacy & Anonymous Research](#5-tor-privacy--anonymous-research)
6. [Advanced Terminal Tools & Shell Integration](#6-advanced-terminal-tools--shell-integration)
7. [Default Runtime Parameters](#7-default-runtime-parameters)
8. [Repository Map](#8-repository-map)

---

## 1. Quickstart

### Prerequisites
- **OS:** Arch Linux or CachyOS
- **GPU:** NVIDIA (CUDA) or Vulkan-supported GPU (tested on RTX 3050 Ti Laptop 4 GB)
- **Tor:** Running locally (`systemctl enable --now tor`)

### One-Command Setup
```bash
./setup.sh
```
`setup.sh` is idempotent. It installs `llama-cpp` with GPU backends via `pacman`, links `cll`, `cll-reaper`, `torsearch`, and `qstop` into `~/.local/bin`, installs UNIX manual pages into `~/.local/share/man/man1`, and downloads default weights.

### Start Using CLL
```bash
# Check system status, active models, and GPU allocation
cll status

# Interactive terminal chat with active model
cll chat

# Start background server
cll server

# Enable automatic lazy-start & idle VRAM reaper daemon
systemctl --user enable --now cll-reaper.service
```

---

## 2. Unified CLI (`cll`)

`cll` is the single command-line interface for controlling all platform capabilities:

| Command | Action | Example |
| :--- | :--- | :--- |
| `cll status` | Display active model, port bindings, processes, and VRAM | `cll status` |
| `cll server` | Start `llama-server` and `cll.opencode_bridge` | `cll server` |
| `cll chat` | Interactive terminal session via `llama-cli` | `cll chat` |
| `cll stop` | Safely terminate all active server, bridge, and CLI processes | `cll stop` |
| `cll logs` | Inspect or follow `cll-reaper` systemd journal logs | `cll logs -f` |
| `cll search` | Anonymous Tor web and `.onion` search engine | `cll search "Linux kernel 6.13 scheduler"` |
| `cll doctor` | Run environment health, port, and OPSEC leak verification | `cll doctor` |
| `cll model list` | List all registered model profiles and download status | `cll model list` |
| `cll model use` | Switch persistent active model profile | `cll model use qwen2.5-coder-3b` |
| `cll model pull` | Download weights from HuggingFace with resume support | `cll model pull qwen2.5-coder-3b` |

### Ad-Hoc Model Override (`-m, --model`)
Any `cll` command accepts `-m <model_id>` to target an alternate model without rewriting configuration:
```bash
cll -m qwen2.5-coder-3b chat
cll -m deepseek-r1-1.5b chat
```

---

## 3. Multi-Model Profiles & Hardware Alignment

The platform is model-agnostic. It supports aligned coding models, reasoning engines, and unrestricted/abliterated models.

### Supported Profiles (4 GB VRAM Tier)

| Profile ID | Model Name | Role | Context | VRAM Footprint | Speed |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `qwen2.5-coder-3b` | Qwen2.5-Coder-3B-Instruct | Clean code & debug (84.1% HumanEval) | 32K | ~1.93 GB (100% GPU) | ~65 tok/s |
| `qwen3-4b` | Huihui-Qwen3-4B-Instruct-Abliterated | Uncensored / OSINT / bypass analysis | 32K | ~2.50 GB (fits VRAM) | ~54 tok/s |
| `deepseek-r1-1.5b` | DeepSeek-R1-Distill-Qwen-1.5B | Ultra-fast math & logical deduction | 32K | ~1.10 GB (100% GPU) | >80 tok/s |
| `qwen2.5-coder-7b` | Qwen2.5-Coder-7B-Instruct | Heavy multi-file refactoring | 16K | ~4.70 GB (GPU+CPU split) | ~14 tok/s |

### Why 4 GB VRAM Optimization Works
1. **Native vs Docker:** Container virtualization (`nvidia-container-toolkit`) costs 150–300 MB of VRAM in CUDA driver overhead. Native execution preserves this memory for model layers.
2. **Quantized KV Cache (`-ctk q4_0 -ctv q4_0`):** Reduces KV cache overhead by 50% compared to fp16, allowing 32K context windows to consume only ~700 MB of VRAM.
3. **Flash Attention (`-fa on`):** Eliminates quadratic attention matrix memory spikes.
4. **Safety Margin (`-fit on -fitt 512`):** Leaves a 512 MiB VRAM buffer to prevent `cudaMalloc` out-of-memory errors from desktop window managers.

---

## 4. Autonomous Coding Agent Integration (OpenCode)

Turnkey compatibility with the [OpenCode](https://opencode.ai) autonomous coding agent CLI and desktop interface.

### Architecture

```
+-------------------------------------------------------------+
|                     OpenCode CLI / TUI                      |
+-------------------------------------------------------------+
                               | HTTP (Port 61230 + Bearer Auth)
                               v
+-------------------------------------------------------------+
|                        cll-reaper                           |
|  - Minimal (2.4 MB RSS) Rust watchdog & auth gateway        |
|  - Drops unauthenticated loopback requests (HTTP 401)       |
|  - Lazy on-demand auto-starter for backend (~2.5s)          |
|  - 15-minute idle VRAM reaper (triggers qstop)              |
+-------------------------------------------------------------+
                               | HTTP (Port 61231)
                               v
+-------------------------------------------------------------+
|                   cll.opencode_bridge                       |
|  - Prunes unused cloud prompts & skill catalogs             |
|  - Injects Senior Systems Architect directives              |
|  - Injects autonomous Tor search tool (tor_search)          |
|  - Recovers raw JSON tool calls emitted without XML tags    |
|  - Maps reasoning effort ('low', 'medium', 'high')          |
|  - Retries connection during CUDA allocation                |
+-------------------------------------------------------------+
                               | HTTP (Port 61232)
                               v
+-------------------------------------------------------------+
|                        llama-server                         |
+-------------------------------------------------------------+
```

### Network Topology & Port Map
- `127.0.0.1:61230` — **Reaper Gateway:** External endpoint targeted by OpenCode with Bearer token authentication (`cll-local-sec-98f2b`).
- `127.0.0.1:61231` — **Agent Bridge:** Internal preprocessing proxy injecting Tor tools and pruning context.
- `127.0.0.1:61232` — **Core Server:** System `llama-server` holding model weights and KV cache.

### Configuration (`opencode.json`)
The repository includes a preconfigured `opencode.json`:
```json
{
  "$schema": "https://opencode.ai/config.json",
  "providers": {
    "local-cll": {
      "name": "Local CLL Gateway",
      "package": "@ai-sdk/openai-compatible",
      "settings": {
        "baseURL": "http://127.0.0.1:61230/v1",
        "apiKey": "cll-local-sec-98f2b"
      },
      "models": {
        "qwen2.5-coder-3b": { "name": "Qwen2.5-Coder 3B", "limit": { "context": 32768, "output": 8192 } },
        "qwen3-4b": { "name": "Qwen3-4B Uncensored", "limit": { "context": 32768, "output": 8192 } }
      }
    }
  },
  "model": "local-cll/qwen2.5-coder-3b"
}
```

---

## 5. Tor Privacy & Anonymous Research

All web exploration is routed strictly through Tor SOCKS5h (`127.0.0.1:9050`) to guarantee zero clearnet leaks.

### Capabilities
- **Strict Fail-Closed OPSEC:** Aborts immediately if Tor daemon is unreachable. All DNS lookups resolve through Tor exit nodes.
- **Traffic Analysis Resistance (`--chaff`):** Emits randomized decoy queries with timing jitter to prevent Tor exit-node profiling.
- **Multi-Engine Cascade:** Aggregates DuckDuckGo HTML, Bing Tor, Wikipedia REST, and Ahmia (`.onion` hidden services).
- **Zero Disk Leakage:** All server runs enforce `--log-disable`.

```bash
# Query web over Tor
cll search "PostgreSQL 17 logical replication internals"

# Verify zero DNS / clearnet leaks
cll doctor
```

---

## 6. Advanced Terminal Tools & Shell Integration

For direct terminal workflows, source `qwen.zsh` in `~/.zshrc`:
```bash
[[ -f "$HOME/Local-LLM-Unsensored/qwen.zsh" ]] && source "$HOME/Local-LLM-Unsensored/qwen.zsh"
```

| Tool | Purpose | Example |
| :--- | :--- | :--- |
| `qwfile` | Codebase & repository analyzer with in-memory RAM symbol resolution | `qwfile src/ "Analyze architecture"` |
| `qwsec` | Security auditor for OWASP, memory safety, and CVE research | `qwsec --offline src/driver.c "Check race conditions"` |
| `qwpipe` | Stream processor for piped stdin without argument limits | `git diff \| qwpipe "Review changes"` |
| `qwcli` | Interactive or single-turn terminal LLM client | `qwcli -c 32 -r 2` |
| `qstop` | Immediate process terminator and VRAM releaser | `qstop` |

---

## 7. Default Runtime Parameters

| Flag | Default | Function |
| :--- | :--- | :--- |
| `-ngl` | `auto` | Automatically offloads maximum layers into free VRAM. |
| `-fit on -fitt 512` | `512` MiB | Reserves a 512 MiB VRAM safety buffer against desktop compositor spikes. |
| `-c` | `32768` | 32K token context window. |
| `-np` | `1` | Single parallel slot preventing duplicated KV cache allocations. |
| `-fa on` | `on` | Enables Flash Attention. |
| `-ctk q4_0 -ctv q4_0` | `q4_0` | Quantizes K and V caches to 4-bit, keeping 32K context under 800 MB VRAM. |
| `-t` | `6` | CPU threads allocated for non-offloaded layers. |

---

## 8. Repository Map

```
Local-LLM-Unsensored/
├── bin/
│   └── cll                      # Unified CLI and multi-model runner
├── cll/
│   ├── doctor.py                # Health & OPSEC leak diagnostic engine
│   ├── inference.py             # HTTP streaming & CLI fallback engine
│   ├── model_manager.py         # Multi-model manifest registry & HuggingFace puller
│   ├── opencode_bridge.py       # OpenAI-compatible proxy with prompt pruning & Tor tools
│   ├── project_analyzer.py      # Hierarchical codebase analyst with chunked notes
│   ├── search.py                # Fail-closed Tor search engine (.onion & clearnet)
│   └── server.py                # Web gateway with CSRF guard
├── tools/
│   └── cll-reaper/              # Minimal Rust watchdog, auth gateway & idle VRAM reaper
├── scripts/
│   ├── cll-reaper.service       # User-level systemd service
│   ├── common.sh                # Shared hardware parameters & preflight checks
│   ├── qstop                    # Process terminator releasing GPU VRAM
│   ├── run-cli.sh               # Terminal CLI runner
│   └── run-server.sh            # Background llama-server & bridge runner
├── shell/                       # Optional zsh functions (qwfile, qwsec, qwpipe)
├── models.json                  # Multi-model configuration manifest
├── opencode.json                # Preconfigured OpenCode provider & policy definition
└── setup.sh                     # Idempotent installer & symlink manager
```
