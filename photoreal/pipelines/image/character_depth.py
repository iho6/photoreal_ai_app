"""character_depth — Klein Base + RefControl depth LoRA (depth map + character ref)."""

from __future__ import annotations

import copy
import json
import random
import re
from pathlib import Path
from typing import Any

from photoreal.config import get_settings
from photoreal.pipelines.base import Pipeline
from photoreal.services.comfy_client import ComfyClient, ComfyClientError, load_workflow_template

WORKFLOW_PATH = Path(__file__).resolve().parent / "workflows" / "character_depth_api.json"
REFCONTROL_LORA = "flux2_klein_9b_refcontrol_depth.safetensors"
TRIGGER = "refcontrol"


def ensure_refcontrol_trigger(prompt: str) -> str:
    """Ensure the RefControl trigger token appears in the positive prompt."""
    text = (prompt or "").strip()
    if not text:
        return TRIGGER
    if re.search(r"\brefcontrol\b", text, flags=re.IGNORECASE):
        return text
    return f"{TRIGGER} {text}"


def patch_character_depth_workflow(
    workflow: dict[str, Any],
    *,
    depth_ref: str,
    reference_ref: str,
    prompt: str,
    width: int,
    height: int,
    seed: int,
    steps: int,
    guidance: float,
    lenovo_strength: float,
    mrpopo_strength: float,
    refcontrol_strength: float,
) -> dict[str, Any]:
    """Patch API-format graph inputs for a character_depth run."""
    w = copy.deepcopy(workflow)
    text = ensure_refcontrol_trigger(prompt)

    w["4"]["inputs"]["strength_model"] = float(lenovo_strength)
    w["4"]["inputs"]["strength_clip"] = float(lenovo_strength)
    w["5"]["inputs"]["strength_model"] = float(mrpopo_strength)
    w["5"]["inputs"]["strength_clip"] = float(mrpopo_strength)
    w["6"]["inputs"]["lora_name"] = REFCONTROL_LORA
    w["6"]["inputs"]["strength_model"] = float(refcontrol_strength)
    w["6"]["inputs"]["strength_clip"] = float(refcontrol_strength)

    w["7"]["inputs"]["text"] = text
    w["9"]["inputs"]["guidance"] = float(guidance)
    w["20"]["inputs"]["image"] = depth_ref
    w["21"]["inputs"]["image"] = reference_ref
    w["26"]["inputs"]["width"] = int(width)
    w["26"]["inputs"]["height"] = int(height)
    w["27"]["inputs"]["seed"] = int(seed)
    w["27"]["inputs"]["steps"] = int(steps)
    return w


class CharacterDepthPipeline(Pipeline):
    """Depth map + character reference → Klein render via RefControl depth LoRA."""

    id = "character_depth"
    domain = "image"

    def validate(
        self,
        *,
        depth_image: str | Path | None = None,
        reference_image: str | Path | None = None,
        prompt: str = "",
        **kwargs: Any,
    ) -> None:
        if not depth_image or not Path(depth_image).is_file():
            raise ValueError("depth_image is required and must be an existing file")
        if not reference_image or not Path(reference_image).is_file():
            raise ValueError(
                "reference_image is required and must be an existing file"
            )
        if prompt is not None and not isinstance(prompt, str):
            raise ValueError("prompt must be a string when provided")

    def run(
        self,
        *,
        depth_image: str | Path,
        reference_image: str | Path,
        prompt: str = TRIGGER,
        width: int = 1024,
        height: int = 1024,
        seed: int | None = None,
        steps: int = 28,
        guidance: float = 4.0,
        lenovo_strength: float = 0.85,
        mrpopo_strength: float = 1.0,
        refcontrol_strength: float = 0.9,
        comfy_url: str | None = None,
        output_dir: str | Path | None = None,
        **kwargs: Any,
    ) -> list[Path]:
        self.validate(
            depth_image=depth_image,
            reference_image=reference_image,
            prompt=prompt,
        )
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
        prompt_graph = {
            k: v for k, v in wf.items() if k != "_meta" and isinstance(v, dict)
        }

        depth_ref = client.upload_image(
            depth_image, subfolder="photoreal_character_depth"
        )
        reference_ref = client.upload_image(
            reference_image, subfolder="photoreal_character_depth"
        )
        seed_val = seed if seed is not None else random.randrange(0, 2**32 - 1)
        final_prompt = ensure_refcontrol_trigger(prompt)

        prompt_graph = patch_character_depth_workflow(
            prompt_graph,
            depth_ref=depth_ref,
            reference_ref=reference_ref,
            prompt=final_prompt,
            width=width,
            height=height,
            seed=seed_val,
            steps=steps,
            guidance=guidance,
            lenovo_strength=lenovo_strength,
            mrpopo_strength=mrpopo_strength,
            refcontrol_strength=refcontrol_strength,
        )

        out_root = (
            Path(output_dir)
            if output_dir
            else Path(settings.data_root) / "outputs" / "character_depth"
        )
        out_root.mkdir(parents=True, exist_ok=True)

        images = client.run_workflow(prompt_graph)
        saved: list[Path] = []
        for name, data in images:
            dest = out_root / name
            dest.write_bytes(data)
            saved.append(dest)

        meta = {
            "pipeline": self.id,
            "prompt": final_prompt,
            "depth_image": str(Path(depth_image).resolve()),
            "reference_image": str(Path(reference_image).resolve()),
            "seed": seed_val,
            "width": width,
            "height": height,
            "steps": steps,
            "guidance": guidance,
            "lenovo_strength": lenovo_strength,
            "mrpopo_strength": mrpopo_strength,
            "refcontrol_strength": refcontrol_strength,
            "outputs": [str(p) for p in saved],
        }
        if saved:
            (out_root / f"{saved[0].stem}_meta.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )
        return saved
