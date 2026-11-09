# GLM Uncensored (Abliterated) Local Inference Setup

Local inference configuration and runner scripts for abliterated (uncensored) GLM models using `llama.cpp` with hybrid CPU + GPU execution on Arch Linux / CachyOS.

---

## 1. Overview of Abliterated Models

Abliterated models remove the refusal direction from the base model's weight matrices via orthogonalization without requiring full fine-tuning. This disables refusal filters while preserving the model's original coding, reasoning, and tool-calling capabilities.

### Model Selection by Hardware Tier

| Hardware Tier | Target VRAM / RAM | Recommended Model | Popular GGUF Repositories | Recommended Quantization |
| :--- | :--- | :--- | :--- | :--- |
| **Low / Mid Hybrid (9B)** | 4–8 GB VRAM + 16 GB RAM | `glm-4-9b-chat-abliterated` | `bartowski/glm-4-9b-chat-abliterated-GGUF`, `mradermacher/glm-4-9b-chat-hf-OBLITERATED-i1-GGUF` | `Q4_K_M` (~5.9 GB) or `IQ3_M` / `Q3_K_M` |
| **Mid / High (30B–32B)** | 16–24 GB VRAM or 32 GB+ RAM | `GLM-4-32B-0414`, `GLM-4.7-Flash`, `GLM-4.5-Air` | `llmfan46/GLM-4-32B-0414-uncensored-heretic-v2-GGUF`, `huihui-ai/Huihui-GLM-4.7-Flash-abliterated` | `Q4_K_M` (~19.7 GB) |
| **Server / Multi-GPU MoE** | 100–230 GB+ Unified/VRAM | `GLM-5.1 / 5.2 / 5.3 Abliterated` | `huihui-ai/Huihui-GLM-5.3-Flash-abliterated-GGUF` (321B), `huihui-ai/Huihui-GLM-5.2-abliterated-GGUF` (754B) | Multi-GPU GGUF / FP8 |

---

## 2. Native `llama.cpp` vs. Docker on 4 GB VRAM Systems

When running `glm-4-9b-chat-abliterated-Q4_K_M.gguf` (~5.9 GB) on a system with 4 GB VRAM and 16 GB RAM, layers are split across the GPU and system RAM. Native execution is strongly preferred over Docker in constrained VRAM environments:

| Criterion | Native (`llama.cpp`) | Docker (`nvidia-container-toolkit`) |
| :--- | :--- | :--- |
| **VRAM Overhead** | Minimal; all free VRAM outside the desktop session is available for model layers. | Container runtime and CUDA context overhead consume an extra 150–300 MB VRAM (2–3 fewer GPU layers). |
| **CPU Performance** | Offloaded CPU layers execute directly with host AVX2 / AVX-512 instruction sets. | Namespace virtualization introduces minor memory bandwidth overhead. |
| **Footprint** | Single binary (`llama-server` or `llama-cli`), no background daemon required. | Requires `nvidia-container-toolkit` and 5–8 GB CUDA container images. |

---

## 3. Repository Structure

| File | Description |
| :--- | :--- |
| `setup.sh` | One-time setup: installs `llama.cpp`, downloads the model, and links the `glm` command into `~/.local/bin` |
| `glm` | Command entry point: `glm server` and `glm cli` |
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
2. Downloads `glm-4-9b-chat-abliterated-Q4_K_M.gguf` from `bartowski/glm-4-9b-chat-abliterated-GGUF` into the project root (or `MODEL_PATH`). An interrupted download resumes on the next run.
3. Links the `glm` command into `~/.local/bin` (or `BIN_DIR`). An existing `glm` that points elsewhere is never overwritten.

Remove the `glm` link again with `./setup.sh --uninstall`; installed packages and the model are kept.

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

Place `glm-4-9b-chat-abliterated-Q4_K_M.gguf` in the project root directory, or specify a custom location via the `MODEL_PATH` environment variable.

---

## 5. Usage

After `setup.sh`, `glm` works from any directory. Without it, `./run-server.sh` and `./run-cli.sh` take the same arguments and environment variables. Options after the command are passed to `llama.cpp` unchanged.

### A. Local Web UI and OpenAI API Server

```bash
glm server
```

- **Web UI:** `http://127.0.0.1:8080`
- **OpenAI API Endpoint:** `http://127.0.0.1:8080/v1`

Override runtime parameters with environment variables when needed:

```bash
NGL=20 CTX=4096 PORT=8080 glm server
```

### B. Interactive Terminal Chat

```bash
glm cli
```

If a custom `rules.md` file exists in the repository root (or is pointed to via `RULES_PATH`), `glm cli` automatically injects it as the system prompt using `-sysf`.

Only one `llama-server` or `llama-cli` instance can hold the GPU at a time. If another one is running, `glm` waits up to 5 seconds for it to exit and then stops with the PIDs to terminate.

### C. Direct Hugging Face Execution (Without Pre-downloading)

Interactive terminal session:

```bash
llama-cli -hf bartowski/glm-4-9b-chat-abliterated-GGUF:Q4_K_M -ngl auto -fit on -fitt 512 -c 8192 -fa on -ctk q8_0 -ctv q8_0 -t 6
```

Local API server:

```bash
llama-server -hf bartowski/glm-4-9b-chat-abliterated-GGUF:Q4_K_M -ngl auto -fit on -fitt 512 -c 8192 -np 1 -fa on -ctk q8_0 -ctv q8_0 -t 6 --port 8080
```

### D. Docker Execution (Optional)

```bash
docker run --gpus all --rm -it -p 8080:8080 -v "$(pwd):/models" ghcr.io/ggml-org/llama.cpp:server-cuda -m /models/glm-4-9b-chat-abliterated-Q4_K_M.gguf -ngl 20 -c 8192 -fa on -ctk q8_0 -ctv q8_0 --host 0.0.0.0 --port 8080
```

---

## 6. Default Runtime Parameters

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `-ngl` | `auto` | Automatically offloads the maximum number of layers that fit into free VRAM (40 total layers in GLM-4-9B). |
| `-fit on -fitt 512` | `512` MiB | Reserves a 512 MiB VRAM safety margin to avoid `cudaMalloc` out-of-memory errors. |
| `-c` | `8192` | Context window size in tokens. |
| `-np` | `1` | Allocates a single parallel slot on `llama-server` to prevent 4x KV cache allocation. |
| `-fa on` | `on` | Enables Flash Attention (`llama.cpp` >= 0.6 requires explicit `on`, `off`, or `auto`). |
| `-ctk q8_0 -ctv q8_0` | `q8_0` | Quantizes K and V caches to 8-bit, saving ~500 MB of VRAM on 8192 context. |
| `-t` | `6` | Number of CPU threads allocated for non-offloaded layers (tuned for 6 physical cores). |
