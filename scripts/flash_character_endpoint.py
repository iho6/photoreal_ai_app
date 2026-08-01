#!/usr/bin/env python3
"""Flash character endpoint: auto-reprompt + photoreal_gen on RTX 4090.

Deploy from WSL/Linux (not native Windows):

  pip install runpod-flash
  export RUNPOD_API_KEY=...
  # Optional: HF_TOKEN for gated downloads if volume incomplete
  flash deploy
  # Endpoint id is auto-resolved (and auto-deployed via WSL if missing)
  # name: photoreal-character-4090

Sync models once onto Network Volume ``photoreal-models`` mounted at
``/runpod-volume/`` — see docs/portal.md.

The Windows portal calls this endpoint via Runpod Serverless HTTP
(``photoreal.flash.client``), not the Flash CLI.
"""

from __future__ import annotations

import asyncio
import json
import os

from runpod_flash import (
    Endpoint,
    GpuType,
    NetworkVolume,
    PodTemplate,
)

from photoreal.flash.volume_layout import (
    VOLUME_NAME,
    VOLUME_SIZE_GB,
    flash_datacenter,
)
from photoreal.flash.worker_character import character_generate_impl

# Datacenter must match volume sync (VOLUME_DATACENTER) and Flash SDK enum.
_DC = flash_datacenter()
_VOLUME = NetworkVolume(
    name=VOLUME_NAME,
    size=VOLUME_SIZE_GB,
    datacenter=_DC,
)


@Endpoint(
    name="photoreal-character-4090",
    gpu=GpuType.NVIDIA_GEFORCE_RTX_4090,
    datacenter=_DC,
    workers=(0, 1),
    idle_timeout=300,
    volume=_VOLUME,
    template=PodTemplate(containerDiskInGb=40),
    execution_timeout_ms=600_000,
    env={
        "HF_TOKEN": os.environ.get("HF_TOKEN", ""),
        "PHOTOREAL_DATA_ROOT": "/runpod-volume/data",
    },
    dependencies=[
        "torch",
        "transformers>=4.57.0",
        "accelerate>=1.0.0",
        "torchvision",
        "Pillow",
        "httpx",
        "websocket-client",
        "huggingface_hub",
    ],
)
def character_generate(prompt: str = "") -> dict:
    """Queue worker entry — input: {\"prompt\": \"...\"}."""
    return character_generate_impl(prompt)


async def main() -> None:
    """Optional local invoke after ``flash deploy`` (Linux/WSL)."""
    demo = os.environ.get("FLASH_DEMO_PROMPT", "a woman in a red coat")
    print(f"Calling photoreal-character-4090 prompt={demo!r}…")
    result = await character_generate(demo)
    # Avoid dumping megabytes of base64 to the console
    summary = {
        "ok": result.get("ok"),
        "rewritten": (result.get("rewritten") or "")[:200],
        "n_images": len(result.get("images_b64") or []),
        "logs_tail": (result.get("logs") or [])[-8:],
        "error": result.get("error"),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
