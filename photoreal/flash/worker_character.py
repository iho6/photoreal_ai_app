"""Character generate logic intended to run on a Flash RTX 4090 worker.

Used by ``flash_apps/character/endpoint.py``. Prefers Network Volume layout
under ``/runpod-volume/`` (see docs/portal.md and flash_apps/character/META.md).
"""

from __future__ import annotations

import base64
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

VOLUME_ROOT = Path("/runpod-volume")
DEFAULT_DATA = VOLUME_ROOT / "data"
DEFAULT_COMFY = VOLUME_ROOT / "runtime" / "comfyui"
DEFAULT_EXTRA_PATHS = VOLUME_ROOT / "comfyui_extra_model_paths.yaml"


def _setup_paths() -> Path:
    """Point photoreal settings at the network volume when present."""
    data = DEFAULT_DATA if DEFAULT_DATA.is_dir() else Path("data")
    os.environ.setdefault("PHOTOREAL_DATA_ROOT", str(data))
    # Ensure cwd-relative imports still resolve models
    if data.is_dir() and not Path("data").exists():
        try:
            Path("data").symlink_to(data, target_is_directory=True)
        except OSError:
            pass
    return data


def _ensure_comfy(log: Callable[[str], None], *, port: int = 8188) -> str:
    url = f"http://127.0.0.1:{port}"
    try:
        from photoreal.services.comfy_client import ComfyClient

        if ComfyClient(base_url=url).health():
            log(f"comfy: already up at {url}")
            return url
    except Exception as exc:  # noqa: BLE001
        log(f"comfy: health check failed ({exc})")

    comfy_root = DEFAULT_COMFY
    if not (comfy_root / "main.py").is_file():
        raise RuntimeError(
            f"ComfyUI not found at {comfy_root}. Sync runtime/comfyui onto the "
            "Network Volume (see docs/portal.md Flash section)."
        )

    extra = DEFAULT_EXTRA_PATHS
    cmd = [
        "python",
        "main.py",
        "--listen",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    if extra.is_file():
        cmd.extend(["--extra-model-paths-config", str(extra)])

    log(f"comfy: starting {' '.join(cmd)} cwd={comfy_root}")
    subprocess.Popen(  # noqa: S603 — controlled worker paths
        cmd,
        cwd=str(comfy_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.time() + 180
    from photoreal.services.comfy_client import ComfyClient

    client = ComfyClient(base_url=url)
    while time.time() < deadline:
        try:
            if client.health():
                log(f"comfy: ready at {url}")
                return url
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    raise RuntimeError(f"ComfyUI failed to become healthy at {url} within 180s")


def character_generate_impl(prompt: str) -> dict[str, Any]:
    """Run reprompt → photoreal_gen; return rewritten + images_b64 + logs."""
    logs: list[str] = []

    def log(msg: str) -> None:
        logs.append(str(msg))

    text = (prompt or "").strip()
    if not text:
        return {"error": "prompt is required", "logs": logs, "images_b64": []}

    data_root = _setup_paths()
    log(f"worker: data_root={data_root}")
    log(f"worker: prompt={text!r}")

    try:
        import torch

        log(
            f"worker: cuda={torch.cuda.is_available()} "
            f"gpu={torch.cuda.get_device_name(0) if torch.cuda.is_available() else ''}"
        )
    except Exception as exc:  # noqa: BLE001
        log(f"worker: torch probe failed ({exc})")

    from photoreal.config import get_settings

    # Refresh settings with PHOTOREAL_DATA_ROOT
    settings = get_settings()
    log(f"worker: settings.data_root={settings.data_root}")

    from photoreal.pipelines.vision.reprompt import (
        CHARACTER_PROMPTS_PATH,
        RepromptPipeline,
    )

    log("reprompt: start")
    rewritten = RepromptPipeline().run(
        prompt=text,
        pack_path=CHARACTER_PROMPTS_PATH,
        unload=True,
        log=log,
    )
    log(f"reprompt: rewritten={rewritten[:500]!r}")

    comfy_url = _ensure_comfy(log)
    out_dir = Path("/tmp/photoreal_character_out")  # noqa: S108 — worker ephemeral
    out_dir.mkdir(parents=True, exist_ok=True)

    from photoreal.pipelines.image.photoreal_gen import PhotorealGenPipeline

    log("gen: start")
    paths = PhotorealGenPipeline().run(
        prompt=rewritten,
        comfy_url=comfy_url,
        output_dir=out_dir,
    )

    images_b64: list[dict[str, str]] = []
    for p in paths:
        path = Path(p)
        raw = path.read_bytes()
        images_b64.append(
            {
                "name": path.name,
                "b64": base64.b64encode(raw).decode("ascii"),
            }
        )
        log(f"gen: encoded {path.name} ({len(raw)} bytes)")

    return {
        "ok": True,
        "rewritten": rewritten,
        "images_b64": images_b64,
        "logs": logs,
    }
