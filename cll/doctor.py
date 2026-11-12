"""
cll/doctor.py - Diagnostic health check CLI for Local-LLM-Unsensored environment.
Verifies Tor SOCKS5h connectivity, exit IP masking, llama-server health, GGUF models,
CLL web gateway, and .qwignore rule integrity.
"""
import os
import sys
import json
import socket
import shutil
import argparse
from typing import List, Dict, Any, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from cll import search as qwsearch
from cll import qwignore


def check_tor_service() -> Dict[str, Any]:
    """Checks whether Tor SOCKS5h daemon is listening on 127.0.0.1:9050."""
    open_port = qwsearch.check_tor_port(port=9050)
    return {
        "component": "Tor SOCKS5h Daemon",
        "target": "127.0.0.1:9050",
        "status": "PASS" if open_port else "FAIL",
        "detail": "Listening and accepting SOCKS5h proxy requests" if open_port else "Offline (Start with: sudo systemctl start tor)"
    }


def check_tor_exit_ip() -> Dict[str, Any]:
    """Verifies Tor IP masking against check.torproject.org."""
    if not qwsearch.check_tor_port(port=9050):
        return {
            "component": "Tor Exit IP Masking",
            "target": "check.torproject.org",
            "status": "FAIL",
            "detail": "Skipped because Tor daemon is unreachable"
        }
    try:
        import requests
        proxies = {"http": "socks5h://127.0.0.1:9050", "https": "socks5h://127.0.0.1:9050"}
        r = requests.get("https://check.torproject.org/api/ip", proxies=proxies, timeout=6)
        if r.status_code == 200:
            data = r.json()
            is_tor = data.get("IsTor", False)
            ip = data.get("IP", "Unknown")
            return {
                "component": "Tor Exit IP Masking",
                "target": "check.torproject.org",
                "status": "PASS" if is_tor else "WARN",
                "detail": f"Active Exit IP: {ip} (Tor Verified: {is_tor})"
            }
    except Exception as e:
        return {
            "component": "Tor Exit IP Masking",
            "target": "check.torproject.org",
            "status": "WARN",
            "detail": f"Tor connection timed out or blocked: {e}"
        }
    return {
        "component": "Tor Exit IP Masking",
        "target": "check.torproject.org",
        "status": "FAIL",
        "detail": "Could not verify Tor exit IP"
    }


def check_llama_server() -> Dict[str, Any]:
    """Checks whether local llama-server daemon is listening on port 8080."""
    try:
        import requests
        r = requests.get("http://127.0.0.1:8080/health", timeout=1.0)
        if r.status_code == 200:
            return {
                "component": "llama-server Daemon",
                "target": "127.0.0.1:8080",
                "status": "PASS",
                "detail": "Healthy and ready for token inference"
            }
    except Exception:
        pass
    return {
        "component": "llama-server Daemon",
        "target": "127.0.0.1:8080",
        "status": "INFO",
        "detail": "Offline (Starts on demand via 'qwserver' or CLL UI Power Bar)"
    }


def check_model_files() -> Dict[str, Any]:
    """Scans for valid GGUF model files in the repository or user models directory."""
    models_found = []
    candidates = [
        REPO_ROOT,
        os.path.expanduser("~/models"),
        os.path.expanduser("~/.local/share/local-llm/models")
    ]
    for c in candidates:
        if os.path.isdir(c):
            try:
                for f in os.listdir(c):
                    if f.endswith(".gguf"):
                        fp = os.path.join(c, f)
                        sz_gb = os.path.getsize(fp) / (1024 ** 3)
                        models_found.append(f"{f} ({sz_gb:.1f} GB)")
            except Exception:
                pass

    if models_found:
        return {
            "component": "GGUF Model Files",
            "target": "Local Storage",
            "status": "PASS",
            "detail": f"Found {len(models_found)} model(s): {', '.join(models_found[:2])}"
        }
    return {
        "component": "GGUF Model Files",
        "target": "Local Storage",
        "status": "WARN",
        "detail": "No .gguf model files detected in standard search paths"
    }


def check_cll_web() -> Dict[str, Any]:
    """Checks if CLL Web Gateway is running on port 41625."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.8)
    is_active = False
    try:
        s.connect(("127.0.0.1", 41625))
        is_active = True
    except Exception:
        pass
    finally:
        s.close()

    return {
        "component": "CLL Web Gateway",
        "target": "127.0.0.1:41625",
        "status": "PASS" if is_active else "INFO",
        "detail": "Active and bound (http://127.0.0.1:41625)" if is_active else "Inactive (Launch with: cll)"
    }


def check_qwignore_rules() -> Dict[str, Any]:
    """Checks active .qwignore and global ~/.config/qw/ignore rules."""
    file_pats, pkg_pats = qwignore.parse_qwignore(REPO_ROOT)
    total_rules = len(file_pats) + len(pkg_pats)
    detail = f"{len(pkg_pats)} package pattern(s), {len(file_pats)} path pattern(s) active"
    return {
        "component": ".qwignore OPSEC Rules",
        "target": ".qwignore & ~/.config/qw/ignore",
        "status": "PASS" if total_rules > 0 else "INFO",
        "detail": detail if total_rules > 0 else "No active ignore rules (See .qwignore.example)"
    }


def check_python_environment() -> Dict[str, Any]:
    """Verifies that essential runtime libraries are installed."""
    required = ["requests", "fastapi", "uvicorn", "bs4"]
    missing = []
    for mod in required:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)

    if missing:
        return {
            "component": "Python Dependencies",
            "target": "sys.modules",
            "status": "FAIL",
            "detail": f"Missing packages: {', '.join(missing)}"
        }
    return {
        "component": "Python Dependencies",
        "target": "sys.modules",
        "status": "PASS",
        "detail": "All critical packages available (requests, fastapi, uvicorn, bs4)"
    }


def run_all_checks() -> List[Dict[str, Any]]:
    return [
        check_tor_service(),
        check_tor_exit_ip(),
        check_llama_server(),
        check_model_files(),
        check_cll_web(),
        check_qwignore_rules(),
        check_python_environment()
    ]


def print_diagnostic_report(checks: List[Dict[str, Any]]) -> int:
    """Formats and prints the diagnostics report as a terminal table."""
    print("\n═══════════════════════════════════════════════════════════════════════════════")
    print(" 🏥 Local-LLM-Unsensored System Diagnostic & OPSEC Doctor")
    print("═══════════════════════════════════════════════════════════════════════════════\n")

    symbols = {
        "PASS": "🟢 PASS",
        "WARN": "🟡 WARN",
        "INFO": "🔵 INFO",
        "FAIL": "🔴 FAIL"
    }

    # Header
    print(f"{'Component':<26} | {'Status':<9} | {'Target':<22} | {'Details'}")
    print(f"{'-'*26}-+-{'-'*9}-+-{'-'*22}-+-{'-'*30}")

    has_fail = False
    for c in checks:
        if c["status"] == "FAIL":
            has_fail = True
        st = symbols.get(c["status"], c["status"])
        print(f"{c['component']:<26} | {st:<9} | {c['target']:<22} | {c['detail']}")

    print("\n═══════════════════════════════════════════════════════════════════════════════\n")
    return 1 if has_fail else 0


def main():
    parser = argparse.ArgumentParser(description="Local-LLM-Unsensored Environment Doctor & Health Check")
    parser.add_argument("--json", action="store_true", help="Output diagnostic results in JSON format")
    args = parser.parse_args()

    checks = run_all_checks()

    if args.json:
        print(json.dumps(checks, indent=2))
        sys.exit(1 if any(c["status"] == "FAIL" for c in checks) else 0)

    code = print_diagnostic_report(checks)
    sys.exit(code)


if __name__ == "__main__":
    main()
