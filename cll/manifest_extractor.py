"""
cll/manifest_extractor.py - Sanitized dependency extractor for package manifests.
Extracts standard open-source dependency names from package manifest files
(requirements.txt, package.json, Cargo.toml, go.mod, CMakeLists.txt, pyproject.toml)
without exposing proprietary code, local paths, or internal architecture.
"""
import os
import re
import sys
from typing import List, Set, Optional

STANDARD_PKG_RE = re.compile(r'^[a-zA-Z0-9_][a-zA-Z0-9_\-\.]{1,40}$')


def extract_manifest_dependencies(project_dir: str) -> List[str]:
    """
    Scans project_dir for recognized package manifests and extracts sanitized,
    top-level external dependency names. Strips all local paths, scoped private
    registries, and internal references. Automatically filters out dependencies
    matching rules in .qwignore.
    """
    dependencies: Set[str] = set()

    # Load .qwignore package exclusion rules
    pkg_patterns = []
    try:
        from cll.qwignore import parse_qwignore, filter_dependencies
        _, pkg_patterns = parse_qwignore(project_dir)
    except Exception:
        pass

    # 1. Python requirements.txt
    req_path = os.path.join(project_dir, "requirements.txt")
    if os.path.isfile(req_path):
        try:
            with open(req_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith(("#", "-", "git+", "http://", "https://", ".")):
                        continue
                    pkg = re.split(r'[=><~;!\[\s]', line)[0].strip().lower()
                    if pkg and STANDARD_PKG_RE.match(pkg):
                        dependencies.add(pkg)
        except Exception:
            pass

    # 2. Node.js package.json
    pkg_json = os.path.join(project_dir, "package.json")
    if os.path.isfile(pkg_json):
        try:
            import json
            with open(pkg_json, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
                for section in ("dependencies", "devDependencies"):
                    for k in data.get(section, {}).keys():
                        k = k.strip().lower()
                        if k.startswith("@") or "/" in k:
                            continue
                        if STANDARD_PKG_RE.match(k):
                            dependencies.add(k)
        except Exception:
            pass

    # 3. Rust Cargo.toml
    cargo_path = os.path.join(project_dir, "Cargo.toml")
    if os.path.isfile(cargo_path):
        try:
            in_deps = False
            with open(cargo_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("[") and "dependencies" in line:
                        in_deps = True
                        continue
                    elif line.startswith("["):
                        in_deps = False
                        continue
                    if in_deps and "=" in line:
                        pkg = line.split("=")[0].strip().lower()
                        if pkg and STANDARD_PKG_RE.match(pkg):
                            dependencies.add(pkg)
        except Exception:
            pass

    # 4. Go go.mod
    go_mod = os.path.join(project_dir, "go.mod")
    if os.path.isfile(go_mod):
        try:
            with open(go_mod, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("require ") or "\t" in line:
                        parts = line.split()
                        for p in parts:
                            if "/" in p:
                                pkg = p.split("/")[-1].lower()
                                if STANDARD_PKG_RE.match(pkg):
                                    dependencies.add(pkg)
        except Exception:
            pass

    # 5. CMakeLists.txt (C/C++ external libraries)
    cmake_path = os.path.join(project_dir, "CMakeLists.txt")
    if os.path.isfile(cmake_path):
        try:
            with open(cmake_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                matches = re.findall(r'find_package\s*\(\s*([a-zA-Z0-9_\-]+)', content, re.IGNORECASE)
                for m in matches:
                    m = m.strip().lower()
                    if m and STANDARD_PKG_RE.match(m):
                        dependencies.add(m)
        except Exception:
            pass

    # 6. Python pyproject.toml
    pyproject = os.path.join(project_dir, "pyproject.toml")
    if os.path.isfile(pyproject):
        try:
            with open(pyproject, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and ("dependencies" in line or line.startswith('"')):
                        pkg = line.split("=")[0].strip(' "\'').lower()
                        if pkg and STANDARD_PKG_RE.match(pkg):
                            dependencies.add(pkg)
        except Exception:
            pass

    # Filter against .qwignore patterns if present
    if pkg_patterns:
        try:
            dependencies = set(filter_dependencies(list(dependencies), pkg_patterns))
        except Exception:
            pass

    # Return top 5 sorted unique dependencies
    return sorted(list(dependencies))[:5]


def extract_code_dependencies(code_content: str, project_dir: Optional[str] = None) -> List[str]:
    """
    Extracts top-level external library references directly from source code
    (e.g., Python `import xyz`, C/C++ `#include <xyz/...>`) without leaking function
    names or local identifiers. Automatically filters out dependencies matching .qwignore.
    """
    dependencies: Set[str] = set()

    # Python imports
    py_matches = re.findall(r'^\s*(?:import|from)\s+([a-zA-Z0-9_]+)', code_content, re.MULTILINE)
    for m in py_matches:
        m = m.strip().lower()
        if m not in ("os", "sys", "re", "json", "time", "datetime", "math", "typing", "collections", "unittest", "tempfile", "subprocess", "shutil"):
            if STANDARD_PKG_RE.match(m):
                dependencies.add(m)

    # C/C++ external headers (angle brackets)
    cpp_matches = re.findall(r'#include\s+<([a-zA-Z0-9_\-]+)(?:/[^>]+)?>', code_content)
    for m in cpp_matches:
        m = m.strip().lower()
        if m not in ("stdio", "stdlib", "string", "iostream", "vector", "map", "memory", "thread", "mutex", "unistd", "fcntl", "errno"):
            if STANDARD_PKG_RE.match(m):
                dependencies.add(m)

    if project_dir:
        try:
            from cll.qwignore import parse_qwignore, filter_dependencies
            _, pkg_patterns = parse_qwignore(project_dir)
            if pkg_patterns:
                dependencies = set(filter_dependencies(list(dependencies), pkg_patterns))
        except Exception:
            pass

    return sorted(list(dependencies))[:4]


def fetch_dependency_research(dependencies: List[str], project_dir: Optional[str] = None) -> str:
    """
    Performs Tor-isolated web research on the given dependency names using cll.search.
    Returns formatted markdown context with security advisories and modern best practices.
    Filters out any dependency matching .qwignore rules before network queries.
    """
    if not dependencies:
        return ""

    if project_dir:
        try:
            from cll.qwignore import parse_qwignore, filter_dependencies
            _, pkg_patterns = parse_qwignore(project_dir)
            if pkg_patterns:
                dependencies = filter_dependencies(dependencies, pkg_patterns)
        except Exception:
            pass

    if not dependencies:
        return ""

    try:
        from cll.search import check_tor_port, execute_search_cascade
    except ImportError:
        try:
            import qwsearch as search_mod
            check_tor_port = search_mod.check_tor_port
            execute_search_cascade = search_mod.execute_search_cascade
        except Exception:
            return ""

    if not check_tor_port():
        sys.stderr.write("[qwfile --web] Notice: Tor SOCKS5h (127.0.0.1:9050) is offline. Skipping external research.\n")
        sys.stderr.flush()
        return ""

    sys.stderr.write(f"[qwfile --web] Performing anonymous Tor research for dependencies: {', '.join(dependencies)}...\n")
    sys.stderr.flush()

    results_md = []
    for pkg in dependencies[:3]:
        query = f"{pkg} security best practices vulnerabilities"
        try:
            hits, engine = execute_search_cascade(query, limit=2)
            if hits:
                pkg_section = [f"#### Dependency: `{pkg}` (via {engine})"]
                for h in hits:
                    title = h.get("title", "")
                    url = h.get("url", "")
                    snip = h.get("snippet", "")[:250].replace("\n", " ")
                    pkg_section.append(f"- **{title}** ({url})\n  {snip}")
                results_md.append("\n".join(pkg_section))
        except Exception as e:
            sys.stderr.write(f"[qwfile --web] Warning: Search query failed for {pkg}: {e}\n")

    if not results_md:
        return ""

    return (
        "\n### 🌐 Anonymous Tor Research Context (External Dependencies)\n"
        "The following advisories and specifications were gathered anonymously over Tor SOCKS5h for detected project dependencies:\n\n"
        + "\n\n".join(results_md)
        + "\n\n---\n"
    )
