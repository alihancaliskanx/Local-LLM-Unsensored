"""
cll/qwignore.py - Exclusion rules parser for files, directories, and package manifests.
Enforces zero-leak OPSEC by filtering proprietary files and internal package dependencies
before local LLM chunking or anonymous Tor web research.
"""
import os
import re
import fnmatch
from typing import List, Set, Tuple, Optional, Dict, Any

STANDARD_PKG_RE = re.compile(r'^[a-zA-Z0-9_][a-zA-Z0-9_\-\.]{1,40}$')


def find_qwignore_root(start_path: str) -> Optional[str]:
    """
    Traverses upward from start_path to find the nearest .qwignore file or repository root (.git).
    Returns the directory path containing the file, or None if not found.
    """
    if not start_path:
        return None
    curr = os.path.abspath(os.path.expanduser(start_path))
    if os.path.isfile(curr):
        curr = os.path.dirname(curr)

    while True:
        if os.path.isfile(os.path.join(curr, ".qwignore")):
            return curr
        if os.path.isdir(os.path.join(curr, ".git")):
            return curr
        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent
    return None


def parse_qwignore(start_path: Optional[str] = None) -> Tuple[List[str], List[str]]:
    """
    Parses .qwignore rules from the project directory (and global ~/.config/qw/ignore if present).
    Returns a tuple of (file_patterns, package_patterns).
    - file_patterns: Glob patterns matching file paths or directories.
    - package_patterns: Glob patterns or exact names matching external package dependencies.
    """
    file_patterns: List[str] = []
    package_patterns: List[str] = []

    paths_to_check: List[str] = []

    # 1. Global user configuration: ~/.config/qw/ignore or ~/.qwignore
    global_cfg = os.path.expanduser("~/.config/qw/ignore")
    if os.path.isfile(global_cfg):
        paths_to_check.append(global_cfg)
    else:
        global_dot = os.path.expanduser("~/.qwignore")
        if os.path.isfile(global_dot):
            paths_to_check.append(global_dot)

    # 2. Project-level .qwignore
    if start_path:
        root_dir = find_qwignore_root(start_path) or (start_path if os.path.isdir(start_path) else os.path.dirname(start_path))
        if root_dir:
            proj_ignore = os.path.join(root_dir, ".qwignore")
            if os.path.isfile(proj_ignore):
                paths_to_check.append(proj_ignore)

    for cfg_path in paths_to_check:
        try:
            with open(cfg_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    # Direct package directive (pkg: or dep:)
                    if line.startswith(("pkg:", "dep:")):
                        pkg_pat = line.split(":", 1)[1].strip().lower()
                        if pkg_pat:
                            package_patterns.append(pkg_pat)
                    else:
                        file_patterns.append(line)
                        # If the rule contains no directory slashes or file extensions,
                        # treat it as a dual pattern matching both files/dirs and package names
                        if "/" not in line and not line.startswith("*.") and "." not in line:
                            package_patterns.append(line.lower())
        except Exception:
            pass

    return file_patterns, package_patterns


def is_package_ignored(pkg_name: str, package_patterns: List[str]) -> bool:
    """
    Returns True if the package name matches any pattern in package_patterns.
    Comparison is case-insensitive and normalizes dashes/underscores (PEP 503 standard).
    """
    if not pkg_name or not package_patterns:
        return False
    pkg_clean = pkg_name.strip().lower()
    pkg_normalized = pkg_clean.replace("_", "-")
    for pat in package_patterns:
        pat_clean = pat.lower()
        pat_normalized = pat_clean.replace("_", "-")
        if fnmatch.fnmatch(pkg_clean, pat_clean) or fnmatch.fnmatch(pkg_normalized, pat_normalized):
            return True
    return False


def is_file_ignored(rel_path: str, file_patterns: List[str], is_dir: bool = False) -> bool:
    """
    Returns True if a relative file path or directory matches any rule in file_patterns.
    Supports directory matching ('dir/'), wildcards ('*.key'), and path components.
    """
    if not rel_path or not file_patterns:
        return False

    norm_path = rel_path.replace(os.sep, "/").strip("/")
    basename = os.path.basename(norm_path)

    for pat in file_patterns:
        clean_pat = pat.strip()
        dir_only = clean_pat.endswith("/")
        clean_pat = clean_pat.rstrip("/")

        if dir_only:
            # Trailing slash indicates directory only
            if is_dir:
                if fnmatch.fnmatch(norm_path, clean_pat) or norm_path.startswith(clean_pat + "/"):
                    return True
                if fnmatch.fnmatch(basename, clean_pat):
                    return True
            else:
                # For files, check if any parent directory segment matches
                parts = norm_path.split("/")
                if len(parts) > 1:
                    parent_dirs = parts[:-1]
                    for i in range(len(parent_dirs)):
                        sub_dir = "/".join(parent_dirs[:i+1])
                        if fnmatch.fnmatch(sub_dir, clean_pat) or fnmatch.fnmatch(parent_dirs[i], clean_pat):
                            return True
            continue

        # Non-directory pattern
        if "/" in clean_pat:
            clean_pat_l = clean_pat.lstrip("/")
            if fnmatch.fnmatch(norm_path, clean_pat_l) or norm_path.startswith(clean_pat_l + "/"):
                return True
        else:
            if fnmatch.fnmatch(basename, clean_pat):
                return True
            # Also check individual segments
            parts = norm_path.split("/")
            for part in parts:
                if fnmatch.fnmatch(part, clean_pat):
                    return True

    return False


def filter_dependencies(dependencies: List[str], package_patterns: List[str]) -> List[str]:
    """Filters out any package matching the ignored package patterns."""
    if not package_patterns:
        return dependencies
    return [p for p in dependencies if not is_package_ignored(p, package_patterns)]
