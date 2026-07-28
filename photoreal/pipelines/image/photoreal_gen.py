"""photoreal_gen — FLUX.2 Klein 9B Base + Lenovo + Mrpopo photoreal via ComfyUI."""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any

from photoreal.config import get_settings
from photoreal.pipelines.base import Pipeline
from photoreal.services.comfy_client import ComfyClient, ComfyClientError, load_workflow_template

WORKFLOW_PATH = Path(__file__).resolve().parent / "workflows" / "photoreal_gen_api.json"
SNOFS_LORA = "optional/klein_snofs_v1_1.safetensors"


class PhotorealGenPipeline(Pipeline):
    """Single Klein 9B Base photoreal text-to-image ability."""

    id = "photoreal_gen"
    domain = "image"

    def validate(
        self,
        *,
        prompt: str = "",
        **kwargs: Any,
    ) -> None:
        if not prompt or not str(prompt).strip():
            raise ValueError("prompt is required and must be non-empty")

    def run(
        self,
        *,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        seed: int | None = None,
        steps: int = 28,
        guidance: float = 4.0,
        lenovo_strength: float = 0.85,
        mrpopo_strength: float = 1.0,
        with_snofs: bool = False,
        snofs_strength: float = 0.8,
        comfy_url: str | None = None,
        output_dir: str | Path | None = None,
        **kwargs: Any,
    ) -> list[Path]:
        """
        Run photoreal_gen against a live ComfyUI server.

        Returns paths to saved PNGs under data/outputs/photoreal_gen/.
        """
        self.validate(prompt=prompt)
        settings = get_settings()
        base = comfy_url or getattr(settings, "comfy_url", "http://127.0.0.1:8188")
        client = ComfyClient(base_url=base)

        if not client.health():
            raise ComfyClientError(
                f"ComfyUI not reachable at {base}. Start it with:\n"
                "  cd runtime/comfyui && python main.py --listen 127.0.0.1 --port 8188 "
                "--extra-model-paths-config ../../comfyui_extra_model_paths.yaml"
            )

        wf = load_workflow_template(WORKFLOW_PATH)
        # Strip non-node metadata
        prompt_graph = {k: v for k, v in wf.items() if k != "_meta" and isinstance(v, dict)}
        prompt_graph = copy.deepcopy(prompt_graph)

        seed_val = seed if seed is not None else random.randrange(0, 2**32 - 1)
        prompt_graph["6"]["inputs"]["text"] = prompt
        prompt_graph["8"]["inputs"]["guidance"] = float(guidance)
        prompt_graph["9"]["inputs"]["width"] = int(width)
        prompt_graph["9"]["inputs"]["height"] = int(height)
        prompt_graph["10"]["inputs"]["seed"] = int(seed_val)
        prompt_graph["10"]["inputs"]["steps"] = int(steps)
        prompt_graph["4"]["inputs"]["strength_model"] = float(lenovo_strength)
        prompt_graph["4"]["inputs"]["strength_clip"] = float(lenovo_strength)
        prompt_graph["5"]["inputs"]["strength_model"] = float(mrpopo_strength)
        prompt_graph["5"]["inputs"]["strength_clip"] = float(mrpopo_strength)

        if with_snofs:
            # Insert optional SNOFS after Mrpopo: rewire sampler model/clip from new node 13
            prompt_graph["13"] = {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["5", 0],
                    "clip": ["5", 1],
                    "lora_name": SNOFS_LORA,
                    "strength_model": float(snofs_strength),
                    "strength_clip": float(snofs_strength),
                },
            }
            prompt_graph["6"]["inputs"]["clip"] = ["13", 1]
            prompt_graph["7"]["inputs"]["clip"] = ["13", 1]
            prompt_graph["10"]["inputs"]["model"] = ["13", 0]

        out_root = Path(output_dir) if output_dir else Path(settings.data_root) / "outputs" / "photoreal_gen"
        out_root.mkdir(parents=True, exist_ok=True)

        images = client.run_workflow(prompt_graph)
        saved: list[Path] = []
        for name, data in images:
            dest = out_root / name
            dest.write_bytes(data)
            saved.append(dest)
        # sidecar params for reproducibility
        meta = {
            "pipeline": self.id,
            "prompt": prompt,
            "seed": seed_val,
            "width": width,
            "height": height,
            "steps": steps,
            "guidance": guidance,
            "lenovo_strength": lenovo_strength,
            "mrpopo_strength": mrpopo_strength,
            "with_snofs": with_snofs,
            "outputs": [str(p) for p in saved],
        }
        (out_root / f"{saved[0].stem}_meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        return saved
