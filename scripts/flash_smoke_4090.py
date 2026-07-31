#!/usr/bin/env python3
"""Flash smoke test: confirm a real RTX 4090 worker.

Deploy from WSL/Linux (Flash CLI is not native on Windows):

  pip install runpod-flash
  export RUNPOD_API_KEY=...   # or: flash login
  flash deploy
  python scripts/flash_smoke_4090.py

Success: printed gpu_name contains \"NVIDIA GeForce RTX 4090\".
"""

from __future__ import annotations

import asyncio
import json

from runpod_flash import Endpoint, GpuType


@Endpoint(
    name="photoreal-smoke-4090",
    gpu=GpuType.NVIDIA_GEFORCE_RTX_4090,
    workers=(0, 1),
    idle_timeout=60,
    dependencies=["torch"],
    execution_timeout_ms=120_000,
)
def smoke_4090() -> dict:
    import torch

    cuda = bool(torch.cuda.is_available())
    gpu_name = torch.cuda.get_device_name(0) if cuda else ""
    return {
        "ok": cuda and "4090" in gpu_name,
        "gpu_name": gpu_name,
        "cuda": cuda,
    }


async def main() -> None:
    print("Calling photoreal-smoke-4090 on Runpod…")
    result = await smoke_4090()
    print(json.dumps(result, indent=2))
    if not result.get("ok"):
        raise SystemExit(
            f"Smoke failed: expected RTX 4090, got {result.get('gpu_name')!r}"
        )
    print("OK — NVIDIA GeForce RTX 4090 confirmed.")


if __name__ == "__main__":
    asyncio.run(main())
