"""Shared environment checks for portal generate / supervisor."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from photoreal.config import get_settings
from photoreal.services.vlm_engine import DEFAULT_LOCAL_DIR

_TORCH_CUDA_CACHE: bool | None = None


def clear_torch_cuda_cache() -> None:
    """Drop cached ``torch.cuda.is_available()`` result (call after reinstall)."""
    global _TORCH_CUDA_CACHE
    _TORCH_CUDA_CACHE = None


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


def nvidia_smi_ok() -> bool:
    from photoreal.portal.torch_cuda import nvidia_smi_ok as _ok

    return _ok()


def describe_torch_cuda() -> dict[str, Any]:
    from photoreal.portal.torch_cuda import describe_torch_cuda as _desc

    return _desc()


def maybe_ensure_cuda_torch(
    *,
    log: Callable[[str], None] | None = None,
) -> bool:
    """
    Ensure the repo ``.venv`` has a modern CUDA torch when an NVIDIA GPU is present.

    Decision uses a **subprocess** probe of the venv (not the portal process’s
    possibly sticky in-process ``+cpu`` import). Reinstall only when the venv
    itself lacks CUDA 12.8+.
    """
    global _TORCH_CUDA_CACHE
    from photoreal.portal.torch_cuda import (
        ensure_cuda_torch,
        format_torch_diag,
        nvidia_smi_ok as smi_ok,
        venv_torch_needs_reinstall,
    )

    def _emit(msg: str) -> None:
        if log:
            try:
                log(msg)
            except Exception:  # noqa: BLE001
                pass

    _emit(f"env: nvidia-smi = {'ok' if smi_ok() else 'missing'}")
    # Sticky in-process torch is informational only (long-lived API may still be +cpu).
    try:
        sticky = describe_torch_cuda()
        _emit(f"env: process torch (sticky) = {format_torch_diag(sticky)}")
    except Exception:  # noqa: BLE001
        pass

    needs, venv_info = venv_torch_needs_reinstall()
    _emit(
        "env: venv torch = "
        f"{venv_info.get('version') or 'missing'} "
        f"cuda_build={venv_info.get('cuda_version') or 'none'} "
        f"available={str(bool(venv_info.get('available'))).lower()}"
    )
    if venv_info.get("error"):
        _emit(f"env: venv torch probe error = {venv_info['error']}")

    if not needs:
        _emit("env: CUDA torch already installed in .venv — skip reinstall")
        _TORCH_CUDA_CACHE = bool(venv_info.get("available"))
        return bool(_TORCH_CUDA_CACHE)

    _emit("env: GPU present but .venv torch lacks CUDA 12.8+ — installing cu128 wheels …")
    ok = ensure_cuda_torch(log=_emit, force=True)
    clear_torch_cuda_cache()
    _TORCH_CUDA_CACHE = bool(ok)
    _emit(f"env: torch_cuda after heal = {str(_TORCH_CUDA_CACHE).lower()}")
    return bool(_TORCH_CUDA_CACHE)


def vlm_model_path() -> Path:
    settings = get_settings()
    path = Path(settings.data_root) / "models" / "vlm" / "Qwen3-VL-8B-Instruct"
    if path.exists():
        return path
    return Path(DEFAULT_LOCAL_DIR)


def comfy_reachable(*, base_url: str | None = None) -> bool:
    from photoreal.services.comfy_client import ComfyClient

    settings = get_settings()
    base = (base_url or getattr(settings, "comfy_url", "http://127.0.0.1:8188")).rstrip(
        "/"
    )
    try:
        return bool(ComfyClient(base_url=base).health())
    except Exception:  # noqa: BLE001
        return False


def assert_generate_env(
    *,
    log: Callable[[str], None] | None = None,
    heal_cuda: bool = True,
) -> dict[str, Any]:
    """
    Fail fast if character Generate cannot run.

    Accepts local CUDA + VLM + Comfy, **or** Runpod API key when the resolved
    backend is ``runpod`` (endpoint id is auto-resolved at generate time).

    When ``heal_cuda`` is true and nvidia-smi sees a GPU but torch has no/old
    CUDA, installs cu128 wheels once before resolving the backend.

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
    if heal_cuda:
        maybe_ensure_cuda_torch(log=log)
    else:
        from photoreal.portal.torch_cuda import format_torch_diag, nvidia_smi_ok as smi_ok

        _emit(f"env: nvidia-smi = {'ok' if smi_ok() else 'missing'}")
        _emit(f"env: {format_torch_diag()}")

    choice = resolve_generate_backend()
    backend = choice["backend"]
    _emit(f"env: backend={backend} ({choice['reason']})")
    _emit(f"env: torch_cuda = {str(choice['cuda']).lower()}")

    if backend == "runpod":
        if not choice["cuda"]:
            from photoreal.portal.torch_cuda import nvidia_smi_ok as smi_ok

            if smi_ok():
                _emit(
                    "env: note: nvidia-smi OK but torch still has no CUDA — "
                    "using Runpod; re-run Launch or check driver / cu128 install logs"
                )
            else:
                _emit(
                    "env: note: no NVIDIA driver on this host "
                    "(portable drive cannot carry CUDA drivers)"
                )
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

    from photoreal.portal.install_probe import models_install_satisfied, models_missing_parts

    if not models_install_satisfied():
        gaps = models_missing_parts()
        preview = "; ".join(gaps[:8]) if gaps else "unknown gaps"
        raise RuntimeError(
            "Local photoreal weights incomplete — fix before Generate burns VLM time. "
            f"Missing: {preview}. "
            "Click Launch in the portal, or run: "
            "python scripts/download_models.py --photoreal-gen"
        )
    _emit("env: photoreal weights = ok")

    vlm_path = vlm_model_path()
    _emit(f"env: vlm_path = {vlm_path}")
    if not vlm_path.exists():
        raise RuntimeError(
            f"VLM weights missing at {vlm_path}. "
            "Run: python scripts/download_models.py --vlm"
        )

    settings = get_settings()
    # Ownership-aware: reuse ours, restart if stale, alt port if alien on :8188.
    _emit("env: comfy — ensuring this repo's Comfy (detect ours vs alien/stale)…")
    from photoreal.portal.supervisor import ensure_repo_comfy

    ensure = ensure_repo_comfy(emit=_emit, timeout=180.0, force=False)
    for n in ensure.get("notes") or []:
        _emit(f"env: {n}")
    comfy_url = ensure.get("comfy_url") or getattr(
        settings, "comfy_url", "http://127.0.0.1:8188"
    )
    comfy_ok = bool(ensure.get("ok")) and comfy_reachable(base_url=comfy_url)
    _emit(
        f"env: comfy after ensure = {'ok' if comfy_ok else 'down'} "
        f"({comfy_url}, port={ensure.get('port')}, "
        f"reused={ensure.get('reused')})"
    )
    if not comfy_ok:
        log_path = (ensure.get("logs") or {}).get("comfy") or "data/logs/comfy.log"
        raise RuntimeError(
            f"ComfyUI not reachable at {comfy_url} after ensure. "
            f"See {log_path}."
        )

    _emit("env: ok (local)")
    return {
        "backend": "local",
        "torch_cuda": True,
        "vlm_path": str(vlm_path),
        "comfy_url": comfy_url,
        "comfy_ok": True,
        "comfy_port": ensure.get("port"),
        "comfy_reused": bool(ensure.get("reused")),
    }
