#!/usr/bin/env python3
"""
cll.project_analyzer - Hierarchical Chunked Codebase Explorer & Analyst for Qwen3-4B
Explores large repositories using progressive directory mapping, chunked module analysis,
persistent note-taking under /tmp/local-llm/, and multi-stage hierarchical synthesis.
"""

import os
import sys
import re
import json
import time
import shutil
import datetime
from typing import List, Dict, Tuple, Optional, Any

IGNORED_DIRS = {
    ".git", "__pycache__", "node_modules", "temp", ".venv", "venv",
    "build", "dist", ".idea", ".vscode", ".cache", "target", "bin", "obj",
    ".pytest_cache", ".ruff_cache", ".mypy_cache"
}

IGNORED_EXTENSIONS = {
    ".gguf", ".bin", ".exe", ".dll", ".so", ".dylib", ".a", ".o", ".pyc",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".zip", ".tar",
    ".gz", ".xz", ".7z", ".pdf", ".woff", ".woff2", ".ttf", ".eot",
    ".mp4", ".mp3", ".lock", ".log", ".iso", ".sqlite", ".db"
}

MAX_CHUNK_CHARS = 24000
MAX_SINGLE_FILE_CHARS = 16000


def sanitize_slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_")
    return slug or "project"


def scan_project_files(project_path: str) -> List[Dict[str, Any]]:
    """Recursively scans repository files while pruning ignored directories, binary extensions, and .qwignore patterns."""
    records = []
    abs_root = os.path.abspath(project_path)

    # Load project-level and global .qwignore file patterns
    file_patterns = []
    try:
        from cll.qwignore import parse_qwignore, is_file_ignored
        file_patterns, _ = parse_qwignore(abs_root)
    except Exception:
        is_file_ignored = lambda p, pats, is_dir=False: False

    for root, dirs, files in os.walk(abs_root):
        dirs[:] = [
            d for d in dirs
            if d not in IGNORED_DIRS and not d.startswith(".")
            and not (file_patterns and is_file_ignored(os.path.relpath(os.path.join(root, d), abs_root), file_patterns, is_dir=True))
        ]

        for fname in sorted(files):
            ext = os.path.splitext(fname)[1].lower()
            if ext in IGNORED_EXTENSIONS or fname.startswith("."):
                continue

            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, abs_root)

            if file_patterns and is_file_ignored(rel_path, file_patterns, is_dir=False):
                continue

            try:
                stat = os.stat(full_path)
                size = stat.st_size
                # Skip files larger than 1 MB entirely to avoid memory bloat
                if size > 1024 * 1024:
                    continue

                records.append({
                    "rel_path": rel_path,
                    "abs_path": full_path,
                    "filename": fname,
                    "ext": ext,
                    "size": size,
                    "dir": os.path.dirname(rel_path) or "root"
                })
            except Exception:
                pass

    return records


def generate_directory_tree_text(records: List[Dict[str, Any]], max_lines: int = 120) -> str:
    """Produces a clean, human-readable directory tree representation."""
    lines = []
    dirs_seen = set()

    for r in records:
        d = r["dir"]
        if d not in dirs_seen:
            dirs_seen.add(d)
            lines.append(f"📁 {d}/")
        lines.append(f"   └── {r['filename']} ({r['size']} B)")
        if len(lines) >= max_lines:
            lines.append(f"   ... ({len(records) - max_lines} more files truncated)")
            break

    return "\n".join(lines)


def partition_into_module_chunks(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Groups project files into logical subsystems/modules with size bounding."""
    groups: Dict[str, List[Dict[str, Any]]] = {}

    for r in records:
        parts = r["rel_path"].split(os.sep)
        if len(parts) == 1:
            key = "root"
        else:
            # Group by top-level or second-level directory (e.g. src/utils or pkg/core)
            if parts[0] in ("libraries", "src", "pkg", "modules") and len(parts) > 2:
                key = f"{parts[0]}/{parts[1]}"
            else:
                key = parts[0]

        groups.setdefault(key, []).append(r)

    chunks = []
    for mod_name, files in sorted(groups.items()):
        current_chunk_files = []
        current_size = 0

        for f in files:
            file_len = min(f["size"], MAX_SINGLE_FILE_CHARS)
            if current_chunk_files and (current_size + file_len > MAX_CHUNK_CHARS):
                chunks.append({
                    "module": mod_name,
                    "chunk_id": f"{mod_name}_{len(chunks) + 1}",
                    "files": current_chunk_files
                })
                current_chunk_files = [f]
                current_size = file_len
            else:
                current_chunk_files.append(f)
                current_size += file_len

        if current_chunk_files:
            chunks.append({
                "module": mod_name,
                "chunk_id": f"{mod_name}_{len(chunks) + 1}",
                "files": current_chunk_files
            })

    return chunks


def read_file_preview(abs_path: str, max_chars: int = MAX_SINGLE_FILE_CHARS) -> str:
    """Reads a UTF-8 text file up to max_chars."""
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars + 10)
            if len(content) > max_chars:
                return content[:max_chars] + f"\n... [Truncated: File exceeds {max_chars} chars] ..."
            return content
    except Exception as e:
        return f"[Failed to read {abs_path}: {e}]"


def setup_notes_workspace(project_name: str, base_notes_dir: str = "/tmp/local-llm") -> Tuple[str, str]:
    """Prepares /tmp/local-llm/<project_name> and a timestamped run directory."""
    os.makedirs(base_notes_dir, exist_ok=True)
    slug = sanitize_slug(project_name)

    project_dir = os.path.join(base_notes_dir, slug)
    notes_dir = os.path.join(project_dir, "notes")
    os.makedirs(notes_dir, exist_ok=True)

    return project_dir, notes_dir


def analyze_chunk_with_llm(
    chunk: Dict[str, Any],
    user_prompt: str,
    project_overview: str,
    inference_fn,
    ctx: int = 32768,
    reasoning_level: int = 2,
    project_root: str = "",
    symbol_cache = None
) -> str:
    """Executes Qwen3-4B inference on an individual module chunk and returns structured notes."""
    mod_name = chunk["module"]
    files = chunk["files"]

    files_text_blocks = []
    dep_contexts = []
    for f in files:
        preview = read_file_preview(f["abs_path"])
        files_text_blocks.append(f"### File: `{f['rel_path']}`\n```\n{preview}\n```")

        if symbol_cache is not None and project_root:
            try:
                from cll import symbol_resolver
                d_ctx, _ = symbol_resolver.build_relevant_dependency_context(
                    target_content=preview,
                    target_file_path=f["abs_path"],
                    project_root=project_root,
                    cache=symbol_cache,
                    max_symbols=8
                )
                if d_ctx and d_ctx not in dep_contexts:
                    dep_contexts.append(d_ctx)
            except Exception:
                pass

    combined_files = "\n\n".join(files_text_blocks)
    dep_block = "\n".join(dep_contexts) + "\n\n" if dep_contexts else ""

    system_prompt = (
        "You are an elite software architect and code auditing assistant. "
        "Analyze the provided module/subsystem code chunk objectively and concisely. "
        "Identify: 1) Core responsibilities and architecture, 2) Key data structures, algorithms, and APIs, "
        "3) Dependencies, 4) Potential bugs, vulnerabilities, or performance bottlenecks. "
        "Output structured markdown notes."
    )

    prompt = (
        f"Project Context:\n{project_overview}\n\n"
        f"Module Under Inspection: `{mod_name}`\n"
        f"User Analysis Goal: {user_prompt}\n\n"
        f"{dep_block}"
        f"Files in this chunk:\n{combined_files}\n\n"
        "Provide thorough architectural and technical notes for this module."
    )

    # In chunk analysis, we collect notes into a string; capture via memory or temporary buffer
    notes = inference_fn(prompt, system_prompt=system_prompt, ctx=ctx, reasoning_level=reasoning_level, capture_output=True)
    return notes or f"# Module: {mod_name}\n(No notes generated)"


def synthesize_final_report(
    project_name: str,
    user_prompt: str,
    tree_text: str,
    all_notes: List[Dict[str, str]],
    inference_fn,
    ctx: int = 32768,
    reasoning_level: int = 2,
    web_research_context: str = ""
) -> str:
    """Aggregates all module notes from /tmp/local-llm and streams the consolidated answer."""
    notes_blocks = []
    for n in all_notes:
        notes_blocks.append(f"## Module Notes: `{n['module']}`\n{n['notes']}")

    aggregated_notes = "\n\n---\n\n".join(notes_blocks)

    system_prompt = (
        "You are a principal software engineer and systems architect. "
        "Synthesize the accumulated subsystem notes into an exhaustive, highly structured final report "
        "that directly answers the user's inquiry. Use markdown headings, bullet points, and code references."
    )

    extra_web = f"\n\n{web_research_context}" if web_research_context else ""
    final_prompt = (
        f"Project: {project_name}\n"
        f"User Request: {user_prompt}\n\n"
        f"High-Level Repository Structure:\n```\n{tree_text[:4000]}\n```\n\n"
        f"Accumulated Subsystem Analysis Notes:\n{aggregated_notes}\n"
        f"{extra_web}\n"
        "Synthesize these findings into the comprehensive final answer for the user."
    )

    sys.stderr.write("\n── [CLL: Generating Consolidated Final Synthesis] ──\n\n")
    sys.stderr.flush()

    final_answer = inference_fn(final_prompt, system_prompt=system_prompt, ctx=ctx, reasoning_level=reasoning_level, capture_output=False)
    return final_answer or ""


def explore_and_analyze_project(
    project_path: str,
    user_prompt: str,
    inference_fn,
    ctx: int = 32768,
    reasoning_level: int = 2,
    base_notes_dir: str = "/tmp/local-llm",
    keep_archive: bool = False,
    export_dir: Optional[str] = None,
    web_research: bool = False
) -> str:
    """
    Main orchestration routine:
    1. Explores directory structure (ls & tree).
    2. Initializes /tmp/local-llm/<project>/ workspace.
    3. Analyzes chunks progressively, logging notes to disk.
    4. Synthesizes and streams final report.
    """
    abs_path = os.path.abspath(os.path.expanduser(project_path))
    project_name = os.path.basename(abs_path) or "root_project"

    sys.stderr.write(f"── [CLL Project Explorer: Initializing scan for '{abs_path}'] ──\n")
    sys.stderr.flush()

    # 1. Scan files
    records = scan_project_files(abs_path)
    if not records:
        sys.stderr.write(f"Error: No analyzable source files found in {abs_path}\n")
        return ""

    total_size_kb = sum(r["size"] for r in records) // 1024
    tree_text = generate_directory_tree_text(records)

    # 2. Partition into chunks
    chunks = partition_into_module_chunks(records)

    # 3. Setup workspace in /tmp/local-llm/<project_name>
    project_dir, notes_dir = setup_notes_workspace(project_name, base_notes_dir=base_notes_dir)

    with open(os.path.join(project_dir, "00_tree.txt"), "w", encoding="utf-8") as f:
        f.write(tree_text)

    project_overview = (
        f"Project Name: {project_name}\n"
        f"Absolute Path: {abs_path}\n"
        f"Total Analyzed Files: {len(records)} ({total_size_kb} KB)\n"
        f"Logical Modules Detected: {len(chunks)}\n"
        f"Scan Timestamp: {datetime.datetime.now().isoformat()}\n"
    )
    with open(os.path.join(project_dir, "01_overview.md"), "w", encoding="utf-8") as f:
        f.write(project_overview)

    sys.stderr.write(f"── [Exploration Complete: {len(records)} files, {len(chunks)} module chunks | Notes: {project_dir}] ──\n")
    sys.stderr.flush()

    # 4. Progressive Chunk Analysis with in-memory SymbolCache
    try:
        from cll import symbol_resolver
        sym_cache = symbol_resolver.SymbolCache()
    except Exception:
        sym_cache = None

    all_notes = []
    try:
        for idx, chunk in enumerate(chunks, 1):
            mod_name = chunk["module"]
            mod_slug = sanitize_slug(mod_name)
            note_filename = f"module_{idx:02d}_{mod_slug}.md"
            note_path = os.path.join(notes_dir, note_filename)

            sys.stderr.write(f"[{idx}/{len(chunks)}] Analyzing module '{mod_name}' ({len(chunk['files'])} files)... ")
            sys.stderr.flush()

            notes_content = analyze_chunk_with_llm(
                chunk=chunk,
                user_prompt=user_prompt,
                project_overview=project_overview,
                inference_fn=inference_fn,
                ctx=ctx,
                reasoning_level=reasoning_level,
                project_root=abs_path,
                symbol_cache=sym_cache
            )

            with open(note_path, "w", encoding="utf-8") as f:
                f.write(f"# Notes: {mod_name}\nGenerated: {datetime.datetime.now().isoformat()}\n\n" + notes_content)

            all_notes.append({
                "module": mod_name,
                "note_path": note_path,
                "notes": notes_content
            })
            sys.stderr.write(f"Saved -> {note_path}\n")
            sys.stderr.flush()
    finally:
        # Purge symbol cache from RAM after project traversal
        if sym_cache is not None:
            sym_cache.clear()

    # 5. Final Consolidated Synthesis with optional anonymous Tor research
    web_context = ""
    if web_research:
        try:
            from cll.manifest_extractor import extract_manifest_dependencies, fetch_dependency_research
            deps = extract_manifest_dependencies(abs_path)
            if deps:
                web_context = fetch_dependency_research(deps, project_dir=abs_path)
        except Exception as e:
            sys.stderr.write(f"[qwfile --web] Notice: Dependency web research skipped: {e}\n")

    final_report = synthesize_final_report(
        project_name=project_name,
        user_prompt=user_prompt,
        tree_text=tree_text,
        all_notes=all_notes,
        inference_fn=inference_fn,
        ctx=ctx,
        reasoning_level=reasoning_level,
        web_research_context=web_context
    )

    final_report_path = os.path.join(project_dir, "final_analysis.md")
    with open(final_report_path, "w", encoding="utf-8") as f:
        f.write(f"# Project Analysis: {project_name}\nPrompt: {user_prompt}\nDate: {datetime.datetime.now().isoformat()}\n\n" + final_report)

    # Manifest for quick inspection
    manifest = {
        "project": project_name,
        "path": abs_path,
        "total_files": len(records),
        "chunks_analyzed": len(chunks),
        "notes_directory": notes_dir,
        "final_report": final_report_path,
        "completed_at": datetime.datetime.now().isoformat()
    }
    with open(os.path.join(project_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    if keep_archive or export_dir:
        dest_dir = export_dir or os.path.expanduser(f"~/.local/share/local-llm/reports/{project_name}_{int(time.time())}")
        try:
            os.makedirs(os.path.dirname(dest_dir), exist_ok=True)
            shutil.copytree(project_dir, dest_dir, dirs_exist_ok=True)
            sys.stderr.write(f"📦 [Permanent Archive Preserved: {dest_dir}]\n")
        except Exception as e:
            sys.stderr.write(f"Warning: Failed to preserve permanent archive ({e})\n")

    sys.stderr.write(f"\n✅ [Analysis Complete | All notes & reports stored at: {project_dir}]\n")
    sys.stderr.flush()

    return final_report
