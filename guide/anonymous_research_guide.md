# Anonymous Technical Research Guide: Tor Integration & Terminal Workflows

## 1. Overview

The `Local-LLM-Unsensored` suite combines local neural inference with anonymous, privacy-preserving research over the Tor network. This guide covers practical command-line workflows for conducting threat intelligence, CVE discovery, and technical protocol analysis without leaking developer identity, network location, or codebase metadata.

---

## 2. Core Tooling Capabilities

| Command | Shorthand | Research Functionality | Privacy Layer |
| :--- | :--- | :--- | :--- |
| `qwsearch` | `qwsr` | Tor-isolated multi-engine web & `.onion` search engine | Tor SOCKS5h (`127.0.0.1:9050`) |
| `qwsearch --chaff`| — | Obfuscated search with random decoy queries & timing jitter | Tor SOCKS5h + Chaff Injection |
| `qwdoctor` | `qw check` | Diagnostic verification of Tor, exit IP, models, and ports | Local + Tor SOCKS5h verification |
| `qwfile --web` | — | Hybrid codebase analyzer with dependency research | Tor SOCKS5h + Local Qwen3-4B |
| `qwsec --web` | — | Hybrid security auditor cross-referencing live CVEs | Tor SOCKS5h + Local Qwen3-4B |
| `qwsec --offline`| — | Air-gapped security audit with zero network requests | Local CVE Cache + Qwen3-4B |
| `cll` | — | Full browser UI with live Tor circuit controls & IP rotation | Tor SOCKS5h + Local FastAPI Gateway |

---

## 3. Verifying Tor Circuit Privacy (Leak Testing)

Before beginning sensitive research, always verify that your traffic exits through a verified Tor node rather than your clearnet IP address.

### Step 1: Automated Leak Test
```bash
qwsearch --leak-test
```
*Expected Output:* Displays the active Tor exit IP, confirmation that `check.torproject.org` validates the Tor connection, and ISP details of the Tor exit relay.

### Step 2: Requesting a New Identity (IP Rotation)
If you require a clean Tor circuit or a fresh exit IP address:
```bash
qwsearch --new-circuit
```
*Mechanism:* Sends a `SIGNAL NEWNYM` command via the Tor control port (`127.0.0.1:9051`) to cycle circuits and establish a fresh entry/exit route.

### Step 3: Manual SOCKS5h Validation
```bash
curl --socks5-hostname 127.0.0.1:9050 https://check.torproject.org/api/ip
```

---

## 4. Practical Workflows & Terminal Patterns

### Workflow A: Hybrid Codebase Audit with Anonymous Dependency Research
Inspect a project directory, parse its dependency manifests, query Tor anonymously for known CVEs affecting those packages, and generate an integrated security recommendation report:

```bash
qwfile --web -c 32 src/ "Analyze project architecture and recommend security hardening based on detected dependencies"
```

### Workflow B: Querying Dark Web & Hidden Services (.onion)
`qwsearch` automatically routes queries containing `.onion` keywords or technical protocol terms through Ahmia (the leading Tor hidden service index):

```bash
qwsearch -r 3 "Onion v3 rendezvous point protocol specifications"
```

```bash
qwsearch --raw "darknet market security post-mortems" | qwsec "Analyze common operational security failures"
```

### Workflow C: Piped Terminal Research Pipeline
Extract compiler warnings or systemd logs, summarize them locally, and feed them into a live Tor technical query:

```bash
journalctl -u tor -n 50 --no-pager | qwpipe "Identify circuit failure reasons"
```

```bash
git diff HEAD~1 | qwsec "Audit commit diff for potential side-channel leaks"
```

### Workflow D: Exporting Research Artifacts
When conducting extensive architecture audits, keep intermediate notes and export the complete markdown report:

```bash
qwfile --web --keep --export /tmp/audit_report src/ "Perform full architecture and security assessment"
```

---

## 5. Security & Isolation Guarantee

1. **Zero Clearnet Fallback:** If Tor shuts down or the SOCKS5h socket on `127.0.0.1:9050` disconnects, all web operations instantly terminate with an `[OPSEC FAIL-CLOSED]` block. Traffic will never silently leak onto your standard network connection.
2. **Local-Only LLM Inference:** All neural text generation is executed by `llama.cpp` using local CPU/GPU resources (`127.0.0.1:8080`). No prompts, code, or weights are shared with third-party cloud servers.
3. **No Persistent Web Tracking:** Web scrapers (`cll/page_reader.py`) and search cascades strip cookies, cache data, and tracking headers. Each request uses a randomized User-Agent header.
