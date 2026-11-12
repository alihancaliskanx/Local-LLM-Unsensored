# OPSEC Guide: Zero-Leak Codebase Search & Dependency Auditing

## 1. Executive Summary & Threat Model

When analyzing proprietary software or private codebases, querying search engines or cloud-based LLM APIs poses severe operational security (OPSEC) risks. Developers frequently leak sensitive intellectual property without realizing it through:

1. **Direct Code Exfiltration:** Pasting proprietary functions, internal domain names, API routes, or private variable names into public search engines.
2. **DNS & Clearnet Metadata Leaks:** Local DNS resolvers leaking queries to local ISPs or enterprise monitors even when using a VPN.
3. **Query Correlation Attacks:** Search engines profiling an IP address and correlating queries about specific framework combinations (e.g., specific custom build tools, internal protocols, or dependency graphs) to identify the company or project.
4. **Third-Party Log Aggregation:** Cloud LLMs logging full prompt contexts to persistent storage, model retraining datasets, or employee review consoles.

`Local-LLM-Unsensored` solves these threats by enforcing a **Strict Local-First, Fail-Closed Tor Isolation Architecture**.

---

## 2. Core Architectural Principles

```
  ┌────────────────────────────────────────────────────────┐
  │                 Local Workspace (RAM)                  │
  │                                                        │
  │  [Project Files / Source Code]                         │
  │           │                                            │
  │           ▼ (Local AST & Regex Scanner)                │
  │  [Manifest Extractor]                                  │
  │     (Pulls ONLY standard open-source package names)    │
  │           │                                            │
  │           ▼ (Strict Sanitization Gate)                 │
  │     Sanitized Queries: ["fastapi", "tokio", "openssl"] │
  │     [PROPRIETARY CODE & LOCAL PATHS DROPPED HERE]      │
  └───────────────────────────┬────────────────────────────┘
                              │
                              ▼
  ┌────────────────────────────────────────────────────────┐
  │         Tor Network Isolation (Port 9050)              │
  │                                                        │
  │  socks5h://127.0.0.1:9050 (Remote DNS Resolution)      │
  │           │                                            │
  │           ├─► DuckDuckGo HTML (Tor Circuit A)          │
  │           ├─► Ahmia .onion (Tor Hidden Service)        │
  │           └─► Wikipedia REST (Tor Circuit B)           │
  │                                                        │
  │  [Advisories & CVE Snippets Retrieved]                 │
  └───────────────────────────┬────────────────────────────┘
                              │
                              ▼
  ┌────────────────────────────────────────────────────────┐
  │              Local Qwen3-4B LLM (RAM/VRAM)             │
  │                                                        │
  │  Context: Local Code (Offline) + Tor Advisories        │
  │  Output:  Synthesized Architecture & Security Report   │
  └────────────────────────────────────────────────────────┘
```

### Principle A: Manifest Sanitization Gate
Private source code is **never** transmitted over any network. When `--web` is activated, the tool scans only formal package manifests (`requirements.txt`, `package.json`, `Cargo.toml`, `go.mod`, `CMakeLists.txt`, `pyproject.toml`). It extracts only standardized, public, top-level library names (e.g. `fastapi`, `tokio`, `openssl`).
- All local paths (`./pkg`, `file://`), internal submodules, and private scoped packages (`@company/secret`) are discarded.
- The outbound query format is strictly generic: `<package_name> security vulnerabilities best practices`.

### Principle B: Fail-Closed Tor SOCKS5h Routing
All external HTTP requests are routed through `socks5h://127.0.0.1:9050`:
- **The trailing 'h' is mandatory:** It guarantees that hostname and DNS resolution occurs strictly on the Tor exit node. Your local machine never performs a clearnet DNS query.
- **Fail-Closed Enforcement:** If the Tor service is offline or unreachable on port 9050, external web requests abort immediately. The tool never falls back to clearnet connections.

### Principle C: In-Memory Ephemeral Symbol Cache
Symbol extraction for C/C++ `#include` and Python `import` statements takes place entirely in volatile system RAM (`SymbolCache`).
- No intermediate database files or symbol tables are persisted to disk.
- RAM caches are purged and garbage-collected as soon as analysis terminates.

### Principle D: Isolated Storage Lifecycle
Intermediate chunk notes during recursive multi-pass directory analysis are written to `/tmp/local-llm/<project>/` (a `tmpfs` RAM-backed filesystem on modern Linux distributions).
- Temporary notes are purged upon completion unless `--keep` is explicitly instructed.

### Principle E: `.qwignore` Exclusion Rules
To safeguard proprietary libraries and confidential directories, repositories can define a `.qwignore` file in the project root (or globally at `~/.config/qw/ignore`):
- **Package Directives (`pkg:<pattern>` or `dep:<pattern>`):** Prevent specific corporate or internal dependencies from being queried over Tor (e.g., `pkg:corp-*`, `pkg:internal-auth`). Normalizes dashes and underscores per PEP 503.
- **File & Directory Directives:** Prevent confidential paths, private keys, certificates, or large binary datasets from being scanned into local LLM context (e.g., `secrets/`, `*.pem`, `*.key`, `data/private/*`).

```ini
# .qwignore example
pkg:corp-*
pkg:internal-telemetry
secrets/
*.pem
*.key
*.env*
```

---

## 3. Developer Safety Checklist Before External Queries

Before running search queries or hybrid audits, verify the following checklist:

| Check | Verification Command | Expected Output |
| :--- | :--- | :--- |
| **Tor SOCKS5h Port** | `qwsearch --leak-test` | Confirms active Tor circuit and non-clearnet exit IP |
| **No Staged Secrets** | `git diff --cached` | No hardcoded API keys, tokens, or private SSH keys |
| **Manifest Isolation** | `qwfile --web -c 32 <path>` | Console logs confirm only generic package names are queried |
| **Local LLM Status** | `qwserver` or `ps aux \| grep llama` | Model running locally on `127.0.0.1:8080` |

---

## 4. Prohibited Actions (Anti-Patterns)

1. **NEVER pass raw code snippets to `qwsearch`:**
   ```bash
   # DANGEROUS: Leaks proprietary code snippet to search engines
   qwsearch "def calculate_proprietary_fee(): ..."
   ```
   **Correct Approach:** Use `qwsec` or `qwfile` offline for private code:
   ```bash
   qwsec src/billing.py "Audit fee calculation for integer overflow"
   ```

2. **NEVER use search terms containing internal hostnames or usernames:**
   ```bash
   # DANGEROUS: Leaks internal infrastructure names
   qwsearch "corp-internal-ldap.prod.company.local CVE"
   ```
   **Correct Approach:** Query generic technology stacks:
   ```bash
   qwsearch "OpenLDAP 2.6 security best practices"
   ```

3. **NEVER disable Tor fail-closed protection in scripts:**
   Always use the built-in `TOR_PROXIES` with `socks5h://` rather than standard HTTP proxies.
