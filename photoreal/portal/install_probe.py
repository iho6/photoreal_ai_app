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


def torch_cuda_flavor() -> str:
    """
    Short tag for the installed torch CUDA build (used in comfy stamp).

    Examples: ``cuda-12.8``, ``cuda-12.4``, ``cpu``, ``missing``.
    """
    try:
        import torch

        ver = getattr(torch.version, "cuda", None)
        if ver:
            return f"cuda-{ver}"
        if torch.cuda.is_available():
            return "cuda-unknown"
        return "cpu"
    except Exception:  # noqa: BLE001
        return "missing"


def comfy_stamp_payload(path: Path | None = None) -> str:
    """Stamp line: ``<req_sha256> <flavor> <requirements_name>``."""
    return f"{requirements_sha256(path)}  {torch_cuda_flavor()}  {COMFY_REQUIREMENTS.name}\n"


def comfy_stamp_matches(path: Path | None = None) -> bool:
    stamp = COMFY_STAMP
    if not stamp.is_file():
        return False
    try:
        parts = stamp.read_text(encoding="utf-8").strip().split()
    except OSError:
        return False
    if not parts:
        return False
    if parts[0] != requirements_sha256(path):
        return False
    # New stamps: ``<sha> <flavor> <requirements_name>``
    if len(parts) >= 2 and parts[1] != COMFY_REQUIREMENTS.name:
        return parts[1] == torch_cuda_flavor()
    # Legacy stamps: ``<sha>  comfyui-photoreal.txt`` (no flavor).
    # Invalidate when an NVIDIA GPU is present (may be stuck on CPU torch).
    try:
        from photoreal.portal.torch_cuda import nvidia_smi_ok

        if nvidia_smi_ok():
            return False
    except Exception:  # noqa: BLE001
        pass
    return True


def write_comfy_stamp(path: Path | None = None) -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    COMFY_STAMP.write_text(comfy_stamp_payload(path), encoding="utf-8")
    return COMFY_STAMP


def comfy_install_satisfied() -> bool:
    if not (comfy_stamp_matches() and comfy_probe_satisfied()):
        return False
    # Even with a matching stamp, heal when the *venv* lacks CUDA (subprocess probe —
    # do not trust sticky in-process +cpu inside the long-lived portal).
    try:
        from photoreal.portal.torch_cuda import venv_torch_needs_reinstall

        needs, _info = venv_torch_needs_reinstall()
        if needs:
            return False
    except Exception:  # noqa: BLE001
        pass
    return True


def models_missing_parts() -> list[str]:
    """
    Human-readable gaps in core photoreal_gen weights (local disk only).

    Empty list means the Launch/Generate local probe is satisfied.
    VLM is not required here (pulled when a full ``--all`` download runs).
    """
    models = REPO_ROOT / "data" / "models"
    klein = models / "flux2" / "klein-base-9b"
    loras = models / "loras"
    missing: list[str] = []
    required = (
        (klein / "ae.safetensors", 100_000_000),
        (klein / "flux-2-klein-base-9b.safetensors", 1_000_000_000),
        (klein / "text_encoder" / "qwen_3_8b.safetensors", 1_000_000_000),
        (loras / "lenovo_flux_klein9b.safetensors", 1_000_000),
        (loras / "mrpopo_photorealistic.safetensors", 1_000_000),
    )
    for path, min_bytes in required:
        try:
            rel = path.relative_to(REPO_ROOT)
        except ValueError:
            rel = path
        try:
            if not path.is_file() or path.stat().st_size < min_bytes:
                missing.append(f"missing/small: {rel.as_posix()}")
        except OSError:
            missing.append(f"unreadable: {rel.as_posix()}")

    te = klein / "text_encoder"
    tok = klein / "tokenizer"
    if not te.is_dir():
        missing.append("missing: data/models/flux2/klein-base-9b/text_encoder/")
    else:
        try:
            if sum(1 for p in te.rglob("*") if p.is_file()) < 3:
                missing.append("incomplete: text_encoder/")
        except OSError:
            missing.append("unreadable: text_encoder/")
    if not tok.is_dir():
        missing.append("missing: data/models/flux2/klein-base-9b/tokenizer/")
    else:
        try:
            if sum(1 for p in tok.rglob("*") if p.is_file()) < 3:
                missing.append("incomplete: tokenizer/")
        except OSError:
            missing.append("unreadable: tokenizer/")
    return missing


def models_install_satisfied() -> bool:
    """
    Fast local-only check: core photoreal_gen weights already on disk.

    Does not hit HF/Civitai. VLM is not required for this probe (Flash / local
    Comfy can proceed; VLM is pulled only when missing and a download runs).
    """
    return not models_missing_parts()


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
