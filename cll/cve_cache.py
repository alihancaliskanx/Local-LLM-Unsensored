"""
cll/cve_cache.py - Offline Security Advisory & Vulnerability Knowledge Cache
Provides air-gapped, zero-network vulnerability intelligence for local security audits (qwsec --offline).
Maps detected external dependencies and code patterns to known CVEs, CWEs, and remediation advice.
"""
import re
from typing import List, Dict, Any, Optional

OFFLINE_ADVISORY_DATABASE: Dict[str, List[Dict[str, str]]] = {
    "openssl": [
        {
            "cve": "CVE-2022-3786",
            "cwe": "CWE-119 (Buffer Overflow)",
            "severity": "HIGH (CVSS 7.5)",
            "summary": "X.509 GeneralName email address punycode decoding buffer overflow.",
            "remediation": "Enforce strict length validation before decode; check return codes on all X509_NAME functions."
        },
        {
            "cve": "CVE-2023-0286",
            "cwe": "CWE-416 (Use-After-Free)",
            "severity": "HIGH (CVSS 7.4)",
            "summary": "X.400 address comparison in X.509 certificate verification triggers pointer reuse.",
            "remediation": "Do not reuse internal ASN.1 pointers after error unwinding."
        }
    ],
    "fastapi": [
        {
            "cve": "CVE-2024-24762",
            "cwe": "CWE-400 (Denial of Service)",
            "severity": "MEDIUM (CVSS 6.5)",
            "summary": "ReDoS in python-multipart parsing unbounded form-data fields.",
            "remediation": "Set explicit file and field size bounds on incoming UploadFile streams."
        }
    ],
    "requests": [
        {
            "cve": "CVE-2023-32681",
            "cwe": "CWE-200 (Information Disclosure)",
            "severity": "MEDIUM (CVSS 6.1)",
            "summary": "Proxy-Authorization header leak across cross-origin HTTP redirects.",
            "remediation": "Strip sensitive headers (Authorization, Proxy-Authorization) before redirect dispatch."
        }
    ],
    "urllib3": [
        {
            "cve": "CVE-2023-45803",
            "cwe": "CWE-200 (Information Exposure)",
            "severity": "MEDIUM (CVSS 6.5)",
            "summary": "Cookie header retained on cross-host 303 See Other redirects.",
            "remediation": "Enforce strict cookie jar isolation per origin domain."
        }
    ],
    "express": [
        {
            "cve": "CVE-2024-29041",
            "cwe": "CWE-79 (Cross-Site Scripting)",
            "severity": "MEDIUM (CVSS 6.1)",
            "summary": "Improper escaping of query parameters in res.redirect().",
            "remediation": "Sanitize and validate redirection targets; do not trust raw req.query in redirect headers."
        }
    ],
    "pyyaml": [
        {
            "cve": "CVE-2020-14343",
            "cwe": "CWE-502 (Arbitrary Code Execution)",
            "severity": "CRITICAL (CVSS 9.8)",
            "summary": "Arbitrary code execution via yaml.load() on untrusted input.",
            "remediation": "Always use yaml.safe_load() or csafeloader; never use unsafe Loader subclasses."
        }
    ],
    "sqlite": [
        {
            "cve": "CVE-2022-35737",
            "cwe": "CWE-787 (Out-of-bounds Write)",
            "severity": "HIGH (CVSS 7.5)",
            "summary": "Integer overflow in sqlite3_str_vappendf() leading to large allocation heap corruption.",
            "remediation": "Restrict formatted string inputs to < 2GB length and validate integer multipliers."
        }
    ],
    "curl": [
        {
            "cve": "CVE-2023-38545",
            "cwe": "CWE-787 (Heap Buffer Overflow)",
            "severity": "CRITICAL (CVSS 9.8)",
            "summary": "SOCKS5 hostname handshake heap buffer overflow on overly long hostnames (>255 chars).",
            "remediation": "Enforce MAX_SOCKS5_HOSTNAME_LEN (255) bounds check before allocating socks buffer."
        }
    ],
    "tokio": [
        {
            "cve": "CVE-2021-45710",
            "cwe": "CWE-416 (Use-After-Free / Race Condition)",
            "severity": "HIGH (CVSS 8.1)",
            "summary": "Data race and memory safety flaw in tokio::sync::mpsc channel buffer destruction.",
            "remediation": "Ensure channel sender and receiver handles synchronize lifecycle through atomic refcounts."
        }
    ],
    "libxml2": [
        {
            "cve": "CVE-2023-45322",
            "cwe": "CWE-416 (Use-After-Free)",
            "severity": "HIGH (CVSS 7.8)",
            "summary": "Use-after-free in xmlTree parser cleanup function during error states.",
            "remediation": "Nullify dangling node pointers immediately upon releasing subtrees."
        }
    ]
}

GENERIC_CWE_GUIDANCE = {
    "cwe-119": {
        "title": "CWE-119: Memory Buffer Boundary Violations",
        "description": "Unchecked writes to buffers (strcpy, sprintf, memcpy, pointer arithmetic).",
        "check": "Verify bounds on all indices and lengths; prefer safe wrappers (snprintf, strlcpy, std::string)."
    },
    "cwe-416": {
        "title": "CWE-416: Use-After-Free",
        "description": "Referencing pointers after memory has been freed/deallocated.",
        "check": "Set pointers to NULL immediately upon free(); employ smart pointers (std::unique_ptr) in C++."
    },
    "cwe-89": {
        "title": "CWE-89: SQL Injection",
        "description": "Constructing dynamic SQL queries via string concatenation.",
        "check": "Use parameterized queries, prepared statements, or ORM parameter binding strictly."
    },
    "cwe-78": {
        "title": "CWE-78: OS Command Injection",
        "description": "Passing unvalidated user input to system(), popen(), or subprocess(shell=True).",
        "check": "Avoid shell=True; pass explicit argument arrays to execv / subprocess.run."
    },
    "cwe-327": {
        "title": "CWE-327: Use of Broken or Risky Cryptographic Algorithms",
        "description": "Using MD5, SHA1, DES, or ECB mode ciphers.",
        "check": "Enforce AES-256-GCM / ChaCha20-Poly1305 for symmetric crypto and SHA-256 / SHA-3 for hashing."
    }
}


def lookup_offline_advisories(dependencies: List[str]) -> str:
    """
    Looks up known vulnerabilities for detected dependency names from the offline database.
    Operates 100% locally with zero network calls.
    """
    if not dependencies:
        return ""

    matched: List[str] = []
    for dep in dependencies:
        dep_clean = dep.lower().replace("_", "-").strip()
        advisories = OFFLINE_ADVISORY_DATABASE.get(dep_clean)
        if advisories:
            for adv in advisories:
                matched.append(
                    f"- **{dep_clean}** [{adv['cve']} - {adv['severity']}]\n"
                    f"  - Flaw: {adv['cwe']} — {adv['summary']}\n"
                    f"  - Safe Remediation: {adv['remediation']}"
                )

    if not matched:
        return ""

    return (
        "\n### 🛡️ Offline Security Advisories (Zero-Network Air-Gapped Cache)\n"
        "The following vulnerability advisories were resolved locally from the offline CVE cache without network queries:\n\n"
        + "\n".join(matched)
        + "\n\n---\n"
    )
