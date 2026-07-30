"""Detect whether Stage-1/Stage-2 pip installs can be skipped."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

from photoreal.portal.paths import COMFY_REQUIREMENTS, LOGS_DIR, REPO_ROOT

COMFY_STAMP = LOGS_DIR / "comfy_reqs.sha256"

PORTAL_MODULES = ("fastapi", "uvicorn", "dotenv")
EXTRAS_MODULES = ("huggingface_hub", "httpx", "websocket", "transformers")
COMFY_PROBE_MODULES = ("aiohttp", "einops", "safetensors")


def modules_importable(names: tuple[str, ...] | list[str], *, python: str | None = None) -> bool:
    """
    Return True if every module imports in this interpreter.

    ``python`` is ignored here (probe runs in-process); Stage-1 scripts probe via subprocess.
    """
    _ = python
    for name in names:
        try:
            importlib.import_module(name)
        except ImportError:
            return False
    return True


def portal_deps_satisfied() -> bool:
    return modules_importable(PORTAL_MODULES)


def extras_deps_satisfied() -> bool:
    return modules_importable(EXTRAS_MODULES)


def comfy_probe_satisfied() -> bool:
    return modules_importable(COMFY_PROBE_MODULES)


def requirements_sha256(path: Path | None = None) -> str:
    p = path or COMFY_REQUIREMENTS
    data = p.read_bytes()
    return hashlib.sha256(data).hexdigest()


def comfy_stamp_matches(path: Path | None = None) -> bool:
    stamp = COMFY_STAMP
    if not stamp.is_file():
        return False
    try:
        recorded = stamp.read_text(encoding="utf-8").strip().split()[0]
    except OSError:
        return False
    return recorded == requirements_sha256(path)


def write_comfy_stamp(path: Path | None = None) -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    digest = requirements_sha256(path)
    COMFY_STAMP.write_text(f"{digest}  {COMFY_REQUIREMENTS.name}\n", encoding="utf-8")
    return COMFY_STAMP


def comfy_install_satisfied() -> bool:
    return comfy_stamp_matches() and comfy_probe_satisfied()


def subprocess_modules_ok(python_exe: str | Path, modules: tuple[str, ...]) -> bool:
    """Run a one-liner import check with an arbitrary interpreter (Stage-1 scripts)."""
    import subprocess

    code = ";".join(f"import {m}" for m in modules)
    r = subprocess.run(
        [str(python_exe), "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        check=False,
    )
    return r.returncode == 0
