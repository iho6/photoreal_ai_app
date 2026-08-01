"""Detect whether Stage-1/Stage-2 pip installs can be skipped."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

from photoreal.portal.paths import COMFY_REQUIREMENTS, LOGS_DIR, REPO_ROOT

COMFY_STAMP = LOGS_DIR / "comfy_reqs.sha256"

PORTAL_MODULES = ("fastapi", "uvicorn", "dotenv", "httpx", "nacl")
EXTRAS_MODULES = ("huggingface_hub", "httpx", "websocket", "transformers")
COMFY_PROBE_MODULES = ("aiohttp", "einops", "safetensors")


def modules_importable(names: tuple[str, ...] | list[str], *, python: str | None = None) -> bool:
    """
    Return True if every module is installed (find_spec — does not import).

    Avoids loading heavy packages like ``transformers`` / ``torch`` just to probe.
    ``python`` is ignored here (probe runs in-process); Stage-1 scripts probe via subprocess.
    """
    _ = python
    for name in names:
        try:
            if importlib.util.find_spec(name) is None:
                return False
        except (ImportError, ModuleNotFoundError, ValueError):
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


def models_install_satisfied() -> bool:
    """
    Fast local-only check: core photoreal_gen weights already on disk.

    Does not hit HF/Civitai. VLM is not required for this probe (Flash / local
    Comfy can proceed; VLM is pulled only when missing and a download runs).
    """
    models = REPO_ROOT / "data" / "models"
    klein = models / "flux2" / "klein-base-9b"
    loras = models / "loras"
    required = (
        (klein / "ae.safetensors", 100_000_000),
        (klein / "flux-2-klein-base-9b.safetensors", 1_000_000_000),
        (loras / "lenovo_flux_klein9b.safetensors", 1_000_000),
        (loras / "mrpopo_photorealistic.safetensors", 1_000_000),
    )
    for path, min_bytes in required:
        try:
            if not path.is_file() or path.stat().st_size < min_bytes:
                return False
        except OSError:
            return False
    te = klein / "text_encoder"
    tok = klein / "tokenizer"
    if not te.is_dir() or not tok.is_dir():
        return False
    try:
        te_files = sum(1 for p in te.rglob("*") if p.is_file())
        tok_files = sum(1 for p in tok.rglob("*") if p.is_file())
    except OSError:
        return False
    return te_files >= 3 and tok_files >= 3


def subprocess_modules_ok(python_exe: str | Path, modules: tuple[str, ...]) -> bool:
    """Run a one-liner import check with an arbitrary interpreter (Stage-1 scripts)."""
    import subprocess

    # find_spec avoids importing torch/transformers in the child too.
    code = (
        "import importlib.util as u;"
        + ";".join(f"assert u.find_spec({m!r})" for m in modules)
    )
    r = subprocess.run(
        [str(python_exe), "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        check=False,
    )
    return r.returncode == 0
