"""Repo paths for the portal package."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = REPO_ROOT / "web"
ENV_PATH = REPO_ROOT / ".env"
LOGS_DIR = REPO_ROOT / "data" / "logs"
COMFY_DIR = REPO_ROOT / "runtime" / "comfyui"
COMFY_REQUIREMENTS = REPO_ROOT / "requirements" / "comfyui-photoreal.txt"
COMFY_EXTRA_LOCAL = REPO_ROOT / "comfyui_extra_model_paths.local.yaml"
COMFY_EXTRA = REPO_ROOT / "comfyui_extra_model_paths.yaml"
DOWNLOAD_SCRIPT = REPO_ROOT / "scripts" / "download_models.py"
VENV_PYTHON_WIN = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
VENV_PYTHON_UNIX = REPO_ROOT / ".venv" / "bin" / "python"


def venv_python() -> Path:
    if VENV_PYTHON_WIN.is_file():
        return VENV_PYTHON_WIN
    if VENV_PYTHON_UNIX.is_file():
        return VENV_PYTHON_UNIX
    return Path("python")


def comfy_extra_config() -> Path:
    if COMFY_EXTRA_LOCAL.is_file():
        return COMFY_EXTRA_LOCAL
    return COMFY_EXTRA
