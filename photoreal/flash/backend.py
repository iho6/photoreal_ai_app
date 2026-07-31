"""Choose local vs Runpod generate backend.

Runpod credentials come only from the portal-managed ``.env``
(``load_credentials``) — not from ad-hoc terminal exports.

No local CUDA ⇒ always Flash (``runpod``), never the local VLM/Comfy path.
"""

from __future__ import annotations

from typing import Any

from photoreal.portal.credentials import apply_env_to_process, load_credentials
from photoreal.portal.env_check import torch_cuda_available


def resolve_generate_backend() -> dict[str, Any]:
    """
    Resolve GENERATE_BACKEND=auto|local|runpod from portal ``.env``.

    Returns dict with keys: backend (\"local\"|\"runpod\"), cuda, runpod_key,
    endpoint_id, reason.
    """
    apply_env_to_process()
    creds = load_credentials()
    mode = (creds.get("generate_backend") or "auto")
    mode = str(mode).strip().lower() or "auto"
    if mode not in ("auto", "local", "runpod"):
        mode = "auto"

    cuda = torch_cuda_available()
    key = (creds.get("runpod_api_key") or "").strip()
    endpoint = (creds.get("flash_character_endpoint") or "").strip()

    # Hard rule: without CUDA, never attempt local generate.
    if not cuda:
        return {
            "backend": "runpod",
            "cuda": False,
            "runpod_key": bool(key),
            "endpoint_id": endpoint,
            "reason": (
                "no local CUDA -> Runpod Flash"
                if mode != "runpod"
                else "GENERATE_BACKEND=runpod (no local CUDA)"
            ),
        }

    if mode == "runpod":
        return {
            "backend": "runpod",
            "cuda": True,
            "runpod_key": bool(key),
            "endpoint_id": endpoint,
            "reason": "GENERATE_BACKEND=runpod",
        }

    # cuda available + auto|local
    return {
        "backend": "local",
        "cuda": True,
        "runpod_key": bool(key),
        "endpoint_id": endpoint,
        "reason": (
            "GENERATE_BACKEND=local"
            if mode == "local"
            else "auto: local CUDA available"
        ),
    }
