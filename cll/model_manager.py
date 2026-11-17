#!/usr/bin/env python3
"""
cll.model_manager — Multi-Model Profile & Manifest Manager for Chat Local LLM (CLL).
Enables seamless model switching, automatic hardware profile resolution, and HuggingFace GGUF downloads.
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path.home() / ".config" / "cll"
ACTIVE_MODEL_FILE = CONFIG_DIR / "active_model"
MANIFEST_PATH = REPO_ROOT / "models.json"


def load_manifest() -> Dict[str, Any]:
    """Loads the model manifest definitions from models.json."""
    if not MANIFEST_PATH.exists():
        return {
            "default": "qwen3-4b",
            "models": {
                "qwen3-4b": {
                    "name": "Qwen3-4B Instruct Abliterated",
                    "repo": "mradermacher/Huihui-Qwen3-4B-Instruct-2507-abliterated-i1-GGUF",
                    "file": "Huihui-Qwen3-4B-Instruct-2507-abliterated.i1-Q4_K_M.gguf",
                    "parameters": "4B",
                    "context": 32768,
                    "fit_target": 768,
                    "gpu_layers": "auto",
                    "reasoning": True,
                    "description": "Default flagship: high-speed, uncensored systems analysis"
                }
            }
        }
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to parse models.json: {e}\n")
        return {"default": "qwen3-4b", "models": {}}


def get_active_model_name() -> str:
    """Returns the identifier of the currently active model."""
    env_model = os.environ.get("CLL_MODEL") or os.environ.get("ACTIVE_MODEL")
    if env_model:
        return env_model.strip()

    if ACTIVE_MODEL_FILE.exists():
        try:
            content = ACTIVE_MODEL_FILE.read_text(encoding="utf-8").strip()
            if content:
                return content
        except Exception:
            pass

    manifest = load_manifest()
    return manifest.get("default", "qwen3-4b")


def get_model_info(model_id: Optional[str] = None) -> Dict[str, Any]:
    """Returns detailed configuration for a specific or active model."""
    manifest = load_manifest()
    mid = model_id or get_active_model_name()
    models = manifest.get("models", {})
    if mid in models:
        info = dict(models[mid])
        info["id"] = mid
        info["path"] = str(REPO_ROOT / info.get("file", ""))
        info["is_installed"] = Path(info["path"]).is_file()
        return info

    # Fallback to default model if requested is missing
    default_id = manifest.get("default", "qwen3-4b")
    if default_id in models:
        info = dict(models[default_id])
        info["id"] = default_id
        info["path"] = str(REPO_ROOT / info.get("file", ""))
        info["is_installed"] = Path(info["path"]).is_file()
        return info

    return {
        "id": "unknown",
        "name": "Custom Model",
        "file": "",
        "path": "",
        "context": 16384,
        "fit_target": 512,
        "gpu_layers": "auto",
        "reasoning": False,
        "is_installed": False
    }


def set_active_model(model_id: str) -> bool:
    """Switches the active model identifier."""
    manifest = load_manifest()
    models = manifest.get("models", {})
    if model_id not in models:
        sys.stderr.write(f"Error: Unknown model '{model_id}'. Run 'cll model list' to see available models.\n")
        return False

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_MODEL_FILE.write_text(model_id.strip() + "\n", encoding="utf-8")
    info = models[model_id]
    filepath = REPO_ROOT / info.get("file", "")
    print(f"Active model set to: {model_id} ({info.get('name', '')})")
    if not filepath.exists():
        print(f"Note: Model weights not found at {filepath}. Run 'cll model pull {model_id}' to download.")
    return True


def list_models() -> None:
    """Prints a structured table of available models and installation status."""
    manifest = load_manifest()
    active = get_active_model_name()
    models = manifest.get("models", {})

    print(f"{'ACTIVE':<8} {'MODEL ID':<20} {'PARAM':<8} {'CONTEXT':<10} {'STATUS':<15} {'NAME'}")
    print("-" * 80)
    for mid, m in models.items():
        is_active = "*" if mid == active else " "
        path = REPO_ROOT / m.get("file", "")
        status = "Installed" if path.is_file() else "Not downloaded"
        param = m.get("parameters", "-")
        ctx = f"{m.get('context', 0) // 1024}K"
        name = m.get("name", "")
        print(f"{is_active:<8} {mid:<20} {param:<8} {ctx:<10} {status:<15} {name}")


def download_model(model_id: str) -> bool:
    """Downloads model weights via curl with resume capability."""
    manifest = load_manifest()
    models = manifest.get("models", {})
    if model_id not in models:
        sys.stderr.write(f"Error: Model '{model_id}' not found in manifest.\n")
        return False

    info = models[model_id]
    repo = info.get("repo")
    filename = info.get("file")
    if not repo or not filename:
        sys.stderr.write(f"Error: Missing repository or filename for model '{model_id}'.\n")
        return False

    target_path = REPO_ROOT / filename
    if target_path.is_file():
        print(f"Model '{model_id}' is already present at {target_path}")
        return True

    url = f"https://huggingface.co/{repo}/resolve/main/{filename}"
    part_path = f"{target_path}.part"
    print(f"Downloading {filename} from {repo}...")
    cmd = ["curl", "-fL", "-C", "-", "-o", part_path, url]
    try:
        subprocess.run(cmd, check=True)
        os.rename(part_path, target_path)
        print(f"Download complete: {target_path}")
        return True
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"Download failed with exit code {e.returncode}. Run again to resume.\n")
        return False
    except Exception as e:
        sys.stderr.write(f"Download error: {e}\n")
        return False


def export_shell_env() -> None:
    """Outputs shell environment assignments for the active model profile."""
    info = get_model_info()
    print(f"export MODEL_PATH=\"{info.get('path', '')}\"")
    print(f"export CTX=\"{info.get('context', 32768)}\"")
    print(f"export FIT_TARGET=\"{info.get('fit_target', 768)}\"")
    print(f"export NGL=\"{info.get('gpu_layers', 'auto')}\"")
    print(f"export ACTIVE_MODEL=\"{info.get('id', 'qwen3-4b')}\"")


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("Usage: cll model <command> [args...]")
        print("\nCommands:")
        print("  list              List all registered models and installation status")
        print("  use <model_id>    Switch the active model profile")
        print("  current           Display currently active model profile details")
        print("  pull <model_id>   Download model weights from HuggingFace")
        print("  env               Print shell environment export statements for active model")
        return

    cmd = args[0]
    if cmd == "list":
        list_models()
    elif cmd == "use":
        if len(args) < 2:
            sys.stderr.write("Usage: cll model use <model_id>\n")
            sys.exit(1)
        if not set_active_model(args[1]):
            sys.exit(1)
    elif cmd == "current":
        info = get_model_info()
        print(json.dumps(info, indent=2))
    elif cmd in ("pull", "download"):
        if len(args) < 2:
            sys.stderr.write("Usage: cll model pull <model_id>\n")
            sys.exit(1)
        if not download_model(args[1]):
            sys.exit(1)
    elif cmd == "env":
        export_shell_env()
    else:
        sys.stderr.write(f"Unknown command: {cmd}. Run 'cll model --help' for usage.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
