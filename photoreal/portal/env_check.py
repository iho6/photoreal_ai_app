"""Shared environment checks for portal generate / supervisor."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from photoreal.config import get_settings
from photoreal.services.vlm_engine import DEFAULT_LOCAL_DIR


def torch_cuda_available() -> bool:
    """Cached — importing torch is expensive on Windows CPU builds."""
    global _TORCH_CUDA_CACHE
    if _TORCH_CUDA_CACHE is not None:
        return _TORCH_CUDA_CACHE
    try:
        import torch

        _TORCH_CUDA_CACHE = bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        _TORCH_CUDA_CACHE = False
    return _TORCH_CUDA_CACHE


_TORCH_CUDA_CACHE: bool | None = None


def vlm_model_path() -> Path:
    settings = get_settings()
    path = Path(settings.data_root) / "models" / "vlm" / "Qwen3-VL-8B-Instruct"
    if path.exists():
        return path
    return Path(DEFAULT_LOCAL_DIR)


def comfy_reachable() -> bool:
    from photoreal.services.comfy_client import ComfyClient

    settings = get_settings()
    base = getattr(settings, "comfy_url", "http://127.0.0.1:8188")
    try:
        return bool(ComfyClient(base_url=base).health())
    except Exception:  # noqa: BLE001
        return False


def assert_generate_env(
    *,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Fail fast if character Generate cannot run.

    Accepts local CUDA + VLM + Comfy, **or** Runpod API key when the resolved
    backend is ``runpod`` (endpoint id is auto-resolved at generate time).

    Raises ``RuntimeError`` with a clear message when a check fails.
    """

    def _emit(msg: str) -> None:
        if log:
            try:
                log(msg)
            except Exception:  # noqa: BLE001
                pass

    from photoreal.flash.backend import resolve_generate_backend

    _emit("env: checking…")
    choice = resolve_generate_backend()
    backend = choice["backend"]
    _emit(f"env: backend={backend} ({choice['reason']})")
    _emit(f"env: torch_cuda = {str(choice['cuda']).lower()}")

    if backend == "runpod":
        if not choice["runpod_key"]:
            raise RuntimeError(
                "No local CUDA — Generate uses Runpod Flash, but the Runpod API key "
                "is missing. Enter it on the portal login page, then retry."
            )
        if choice["endpoint_id"]:
            _emit(f"env: flash_endpoint = {choice['endpoint_id']} (cached)")
        else:
            _emit("env: flash_endpoint = auto (resolve at generate)")
        _emit("env: ok (runpod)")
        return {
            "backend": "runpod",
            "torch_cuda": bool(choice["cuda"]),
            "endpoint_id": choice["endpoint_id"] or None,
        }

    # local path (only reached when CUDA is available)
    if not choice["cuda"]:
        raise RuntimeError(
            "Internal error: local generate selected without CUDA. "
            "Enter Runpod credentials on the portal to use Flash."
        )

    vlm_path = vlm_model_path()
    _emit(f"env: vlm_path = {vlm_path}")
    if not vlm_path.exists():
        raise RuntimeError(
            f"VLM weights missing at {vlm_path}. "
            "Run: python scripts/download_models.py --vlm"
        )

    settings = get_settings()
    comfy_url = getattr(settings, "comfy_url", "http://127.0.0.1:8188")
    comfy_ok = comfy_reachable()
    _emit(f"env: comfy = {'ok' if comfy_ok else 'down'} ({comfy_url})")
    if not comfy_ok:
        raise RuntimeError(
            f"ComfyUI not reachable at {comfy_url}. "
            "Start it via Launch (or ensure Comfy is running on :8188)."
        )

    _emit("env: ok (local)")
    return {
        "backend": "local",
        "torch_cuda": True,
        "vlm_path": str(vlm_path),
        "comfy_url": comfy_url,
        "comfy_ok": True,
    }
