"""Minimal ComfyUI HTTP/WS client for photoreal_gen."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import httpx


class ComfyClientError(RuntimeError):
    pass


class ComfyClient:
    """Talk to a running ComfyUI server (default http://127.0.0.1:8188)."""

    def __init__(self, base_url: str = "http://127.0.0.1:8188", timeout: float = 600.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def health(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/system_stats", timeout=5.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def queue_prompt(self, prompt: dict[str, Any], client_id: str | None = None) -> str:
        client_id = client_id or str(uuid.uuid4())
        payload = {"prompt": prompt, "client_id": client_id}
        r = httpx.post(f"{self.base_url}/prompt", json=payload, timeout=60.0)
        if r.status_code != 200:
            raise ComfyClientError(f"Comfy /prompt failed: {r.status_code} {r.text}")
        data = r.json()
        if "error" in data:
            raise ComfyClientError(f"Comfy rejected prompt: {data}")
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise ComfyClientError(f"No prompt_id in response: {data}")
        return prompt_id

    def wait_history(self, prompt_id: str) -> dict[str, Any]:
        """Poll history until the prompt finishes."""
        import time

        deadline = time.time() + self.timeout
        while time.time() < deadline:
            r = httpx.get(f"{self.base_url}/history/{prompt_id}", timeout=30.0)
            r.raise_for_status()
            hist = r.json()
            if prompt_id in hist:
                return hist[prompt_id]
            time.sleep(0.5)
        raise ComfyClientError(f"Timed out waiting for prompt_id={prompt_id}")

    def download_image(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        r = httpx.get(f"{self.base_url}/view", params=params, timeout=120.0)
        r.raise_for_status()
        return r.content

    def run_workflow(self, prompt: dict[str, Any]) -> list[tuple[str, bytes]]:
        """Queue workflow, wait, return list of (filename, png_bytes)."""
        prompt_id = self.queue_prompt(prompt)
        hist = self.wait_history(prompt_id)
        outputs = hist.get("outputs") or {}
        images: list[tuple[str, bytes]] = []
        for node_out in outputs.values():
            for img in node_out.get("images") or []:
                name = img["filename"]
                data = self.download_image(
                    name,
                    subfolder=img.get("subfolder") or "",
                    folder_type=img.get("type") or "output",
                )
                images.append((name, data))
        if not images:
            raise ComfyClientError(
                f"No images in history for {prompt_id}: {json.dumps(hist)[:500]}"
            )
        return images


def load_workflow_template(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
