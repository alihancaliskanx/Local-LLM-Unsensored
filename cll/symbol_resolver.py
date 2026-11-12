#!/usr/bin/env python3
"""
cll.symbol_resolver — In-Memory Dependency Symbol Resolver for Qwen3-4B
Fast, AST/regex-based symbol table extractor that resolves imports/includes,
caches class/function/variable signatures in RAM, and injects relevant definitions
into local LLM file analysis prompts without bloating context or wasting GPU tokens.
"""

import os
import re
import ast
import sys
from typing import Dict, List, Set, Optional, Tuple, Any

class SymbolCache:
    """In-memory symbol table cache holding structured class/function/variable signatures."""
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}

    def has(self, file_path: str) -> bool:
        return file_path in self._cache

    def get(self, file_path: str) -> Optional[Dict[str, Any]]:
        return self._cache.get(file_path)

    def set(self, file_path: str, data: Dict[str, Any]) -> None:
        self._cache[file_path] = data

    def clear(self) -> None:
        """Purges all cached symbols from RAM."""
        self._cache.clear()

    def stats(self) -> Dict[str, Any]:
        total_symbols = sum(len(d.get("symbols", [])) for d in self._cache.values())
        return {
            "cached_files": len(self._cache),
            "total_symbols": total_symbols,
            "keys": list(self._cache.keys())
        }


def extract_includes_and_imports(content: str, ext: str) -> List[str]:
    """Finds referenced local imports/includes from file content."""
    dependencies = []
    ext = ext.lower()

    if ext in (".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"):
        # Match #include "..." (local headers) and #include <libraries/...>
        matches = re.findall(r'#\s*include\s*["<]([a-zA-Z0-9_./\-]+)[">]', content)
        for m in matches:
            # Skip standard library headers without extension or in sys dirs
            if m.startswith(("std", "sys/", "net/", "arpa/", "bits/")) or "." not in os.path.basename(m):
                continue
            dependencies.append(m)

    elif ext == ".py":
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        dependencies.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if mod:
                        dependencies.append(mod)
                        for alias in node.names:
                            dependencies.append(f"{mod}.{alias.name}")
                    else:
                        for alias in node.names:
                            dependencies.append(alias.name)
        except Exception:
            # Fallback regex if syntax error in incomplete code
            matches = re.findall(r'^(?:from|import)\s+([a-zA-Z0-9_.]+)', content, re.MULTILINE)
            dependencies.extend(matches)

    return list(dict.fromkeys(dependencies))


def resolve_dependency_filepath(dep_str: str, current_file_path: str, project_root: str) -> Optional[str]:
    """Resolves an include/import string to an absolute file path on disk."""
    current_dir = os.path.dirname(os.path.abspath(current_file_path))
    project_root = os.path.abspath(project_root)

    # 1. Check relative to current file
    cand1 = os.path.normpath(os.path.join(current_dir, dep_str))
    if os.path.isfile(cand1):
        return cand1

    # 2. Check relative to project root
    cand2 = os.path.normpath(os.path.join(project_root, dep_str))
    if os.path.isfile(cand2):
        return cand2

    # 3. For C/C++, search common include subdirs (libraries/, include/, src/)
    for subdir in ("libraries", "include", "src", "inc", "core"):
        cand3 = os.path.normpath(os.path.join(project_root, subdir, dep_str))
        if os.path.isfile(cand3):
            return cand3

    # 4. For Python, convert dots to path (e.g. cll.security -> cll/security.py or cll/__init__.py)
    py_rel = dep_str.replace(".", os.sep)
    for base in (project_root, current_dir):
        # Direct .py file
        cand_py = os.path.normpath(os.path.join(base, py_rel + ".py"))
        if os.path.isfile(cand_py):
            return cand_py
        # Package directory with __init__.py
        cand_init = os.path.normpath(os.path.join(base, py_rel, "__init__.py"))
        if os.path.isfile(cand_init):
            return cand_init

    return None


def extract_symbols_from_cpp_header(content: str) -> List[Dict[str, str]]:
    """Extracts classes, structs, enums, and method declarations from C/C++ header content."""
    symbols = []

    # Strip multi-line comments and single-line comments
    clean = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    clean = re.sub(r'//.*', '', clean)

    # 1. Classes and Structs
    class_pattern = re.compile(
        r'\b(class|struct)\s+([a-zA-Z0-9_]+)(?:\s*:\s*[^{;]+)?\s*\{([^}]*)\};',
        re.DOTALL
    )
    for match in class_pattern.finditer(clean):
        kind = match.group(1)
        name = match.group(2)
        body = match.group(3)

        # Extract public member function signatures and variables
        members = []
        for line in body.splitlines():
            line_s = line.strip()
            # Match member variable or method declaration ending in ';'
            if line_s and not line_s.startswith(("private:", "protected:", "public:")) and ";" in line_s:
                decl = line_s.split(";")[0].strip()
                if len(decl) < 120 and "(" in decl:
                    members.append(decl)
                elif len(decl) < 80 and not decl.startswith(("#", "//", "/*")):
                    members.append(decl)
            if len(members) >= 6:
                members.append("...")
                break

        summary = f"{kind} {name} {{ " + "; ".join(members[:6]) + " };" if members else f"{kind} {name};"
        symbols.append({
            "name": name,
            "kind": kind,
            "signature": summary
        })

    # 2. Enums
    enum_pattern = re.compile(r'\benum\s+(?:class\s+)?([a-zA-Z0-9_]+)\s*\{([^}]*)\};', re.DOTALL)
    for match in enum_pattern.finditer(clean):
        name = match.group(1)
        values = [v.strip().split("=")[0].strip() for v in match.group(2).split(",") if v.strip()]
        val_str = ", ".join(values[:5]) + ("..." if len(values) > 5 else "")
        symbols.append({
            "name": name,
            "kind": "enum",
            "signature": f"enum {name} {{ {val_str} }};"
        })

    # 3. Top-level function declarations (strip classes/structs first to avoid matching member methods)
    no_classes = re.sub(r'\b(class|struct)\s+[a-zA-Z0-9_]+(?:\s*:\s*[^{;]+)?\s*\{[^}]*\};', '', clean)
    fn_pattern = re.compile(r'^[ \t]*([a-zA-Z0-9_*&:]+\s+[a-zA-Z0-9_:]+\s*\([^;{}]*\)\s*(?:const)?);', re.MULTILINE)
    for match in fn_pattern.finditer(no_classes):
        sig = match.group(1).strip()
        fn_name_m = re.search(r'\b([a-zA-Z0-9_]+)\s*\(', sig)
        if fn_name_m:
            fn_name = fn_name_m.group(1)
            if fn_name not in ("if", "for", "while", "switch"):
                symbols.append({
                    "name": fn_name,
                    "kind": "function",
                    "signature": sig + ";"
                })

    return symbols


def extract_symbols_from_python(content: str) -> List[Dict[str, str]]:
    """Extracts classes, methods, top-level functions, and constants from Python content via AST."""
    symbols = []
    try:
        tree = ast.parse(content)
    except Exception:
        return symbols

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    args = [a.arg for a in item.args.args]
                    methods.append(f"{item.name}({', '.join(args)})")
                if len(methods) >= 5:
                    methods.append("...")
                    break
            symbols.append({
                "name": node.name,
                "kind": "class",
                "signature": f"class {node.name}: [{', '.join(methods)}]"
            })
        elif isinstance(node, ast.FunctionDef):
            args = [a.arg for a in node.args.args]
            symbols.append({
                "name": node.name,
                "kind": "function",
                "signature": f"def {node.name}({', '.join(args)}): ..."
            })
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    symbols.append({
                        "name": target.id,
                        "kind": "constant",
                        "signature": f"{target.id} = ..."
                    })

    return symbols


def parse_and_cache_file_symbols(file_path: str, cache: SymbolCache) -> Dict[str, Any]:
    """Reads a dependency file, extracts its symbols, and stores them in RAM cache."""
    abs_path = os.path.abspath(file_path)
    cached = cache.get(abs_path)
    if cached is not None:
        return cached

    ext = os.path.splitext(abs_path)[1].lower()
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(64000)
    except Exception:
        content = ""

    symbols = []
    if ext in (".h", ".hpp", ".c", ".cpp", ".cc"):
        symbols = extract_symbols_from_cpp_header(content)
    elif ext == ".py":
        symbols = extract_symbols_from_python(content)

    data = {
        "file": abs_path,
        "filename": os.path.basename(abs_path),
        "symbols": symbols
    }
    cache.set(abs_path, data)
    return data


def build_relevant_dependency_context(
    target_content: str,
    target_file_path: str,
    project_root: str,
    cache: SymbolCache,
    max_symbols: int = 15
) -> Tuple[str, Dict[str, Any]]:
    """
    1. Extracts imports/includes from target_content.
    2. Resolves paths on disk.
    3. Loads symbols into RAM (or retrieves from cache).
    4. Filters to only symbols explicitly referenced in target_content.
    5. Returns formatted markdown context and metrics.
    """
    ext = os.path.splitext(target_file_path)[1].lower()
    raw_deps = extract_includes_and_imports(target_content, ext)

    resolved_files = []
    for dep in raw_deps:
        fpath = resolve_dependency_filepath(dep, target_file_path, project_root)
        if fpath and fpath not in resolved_files and fpath != os.path.abspath(target_file_path):
            resolved_files.append(fpath)

    # Collect symbols from all resolved files
    matched_symbols = []
    seen_names = set()

    for rfile in resolved_files:
        dep_data = parse_and_cache_file_symbols(rfile, cache)
        fname = dep_data["filename"]

        for sym in dep_data["symbols"]:
            sname = sym["name"]
            # Relevance filter: Only include symbols mentioned in target code
            if sname not in seen_names and re.search(r'\b' + re.escape(sname) + r'\b', target_content):
                seen_names.add(sname)
                matched_symbols.append((fname, sym))
                if len(matched_symbols) >= max_symbols:
                    break
        if len(matched_symbols) >= max_symbols:
            break

    if not matched_symbols:
        return "", {
            "dependencies_found": len(raw_deps),
            "dependencies_resolved": len(resolved_files),
            "symbols_injected": 0,
            "cache_stats": cache.stats()
        }

    lines = ["### 🧬 Relevant Imported/Included Symbol Definitions (In-Memory Resolved):"]
    for fname, sym in matched_symbols:
        lines.append(f"- **`{sym['name']}`** (`{sym['kind']}` from `{fname}`): `{sym['signature']}`")

    context_block = "\n".join(lines) + "\n\n"
    metrics = {
        "dependencies_found": len(raw_deps),
        "dependencies_resolved": len(resolved_files),
        "symbols_injected": len(matched_symbols),
        "cache_stats": cache.stats()
    }
    return context_block, metrics
