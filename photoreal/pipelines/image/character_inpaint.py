"""character_inpaint — Klein Base masked edit (scene + mask + character ref)."""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any

from photoreal.config import get_settings
from photoreal.pipelines.base import Pipeline
from photoreal.services.comfy_client import ComfyClient, ComfyClientError, load_workflow_template

WORKFLOW_PATH = Path(__file__).resolve().parent / "workflows" / "character_inpaint_api.json"

DEFAULT_PROMPT = (
    "replace the person with the reference character, "
    "match scene lighting and camera, photorealistic"
)


def patch_character_inpaint_workflow(
    workflow: dict[str, Any],
    *,
    scene_ref: str,
    mask_ref: str,
    reference_ref: str,
    prompt: str,
    seed: int,
    steps: int,
    guidance: float,
    denoise: float,
    lenovo_strength: float,
    mrpopo_strength: float,
    mask_channel: str = "red",
    mask_expand: int = 6,
    mask_feather: int = 8,
) -> dict[str, Any]:
    """Patch API-format graph inputs for a character_inpaint run."""
    w = copy.deepcopy(workflow)
    text = (prompt or "").strip() or DEFAULT_PROMPT

    w["4"]["inputs"]["strength_model"] = float(lenovo_strength)
    w["4"]["inputs"]["strength_clip"] = float(lenovo_strength)
    w["5"]["inputs"]["strength_model"] = float(mrpopo_strength)
    w["5"]["inputs"]["strength_clip"] = float(mrpopo_strength)

    w["6"]["inputs"]["text"] = text
    w["8"]["inputs"]["guidance"] = float(guidance)
    w["20"]["inputs"]["image"] = scene_ref
    w["21"]["inputs"]["image"] = reference_ref
    w["22"]["inputs"]["image"] = mask_ref
    w["22"]["inputs"]["channel"] = mask_channel
    w["23"]["inputs"]["expand"] = int(mask_expand)
    feather = int(mask_feather)
    w["24"]["inputs"]["left"] = feather
    w["24"]["inputs"]["top"] = feather
    w["24"]["inputs"]["right"] = feather
    w["24"]["inputs"]["bottom"] = feather
    w["30"]["inputs"]["seed"] = int(seed)
    w["30"]["inputs"]["steps"] = int(steps)
    w["30"]["inputs"]["denoise"] = float(denoise)
    return w


class CharacterInpaintPipeline(Pipeline):
    """Scene plate + person mask + character reference → scene-lit character bake."""

    id = "character_inpaint"
    domain = "image"

    def validate(
        self,
        *,
        scene_image: str | Path | None = None,
        mask_image: str | Path | None = None,
        reference_image: str | Path | None = None,
        prompt: str = "",
        **kwargs: Any,
    ) -> None:
        if not scene_image or not Path(scene_image).is_file():
            raise ValueError("scene_image is required and must be an existing file")
        if not mask_image or not Path(mask_image).is_file():
            raise ValueError("mask_image is required and must be an existing file")
        if not reference_image or not Path(reference_image).is_file():
            raise ValueError(
                "reference_image is required and must be an existing file"
            )
        if prompt is not None and not isinstance(prompt, str):
            raise ValueError("prompt must be a string when provided")

    def run(
        self,
        *,
        scene_image: str | Path,
        mask_image: str | Path,
        reference_image: str | Path,
        prompt: str = DEFAULT_PROMPT,
        seed: int | None = None,
        steps: int = 28,
        guidance: float = 4.0,
        denoise: float = 0.95,
        lenovo_strength: float = 0.85,
        mrpopo_strength: float = 1.0,
        mask_channel: str = "red",
        mask_expand: int = 6,
        mask_feather: int = 8,
        comfy_url: str | None = None,
        output_dir: str | Path | None = None,
        **kwargs: Any,
    ) -> list[Path]:
        self.validate(
            scene_image=scene_image,
            mask_image=mask_image,
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

        sub = "photoreal_character_inpaint"
        scene_ref = client.upload_image(scene_image, subfolder=sub)
        mask_ref = client.upload_image(mask_image, subfolder=sub)
        reference_ref = client.upload_image(reference_image, subfolder=sub)
        seed_val = seed if seed is not None else random.randrange(0, 2**32 - 1)
        final_prompt = (prompt or "").strip() or DEFAULT_PROMPT

        prompt_graph = patch_character_inpaint_workflow(
            prompt_graph,
            scene_ref=scene_ref,
            mask_ref=mask_ref,
            reference_ref=reference_ref,
            prompt=final_prompt,
            seed=seed_val,
            steps=steps,
            guidance=guidance,
            denoise=denoise,
            lenovo_strength=lenovo_strength,
            mrpopo_strength=mrpopo_strength,
            mask_channel=mask_channel,
            mask_expand=mask_expand,
            mask_feather=mask_feather,
        )

        out_root = (
            Path(output_dir)
            if output_dir
            else Path(settings.data_root) / "outputs" / "character_inpaint"
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
            "scene_image": str(Path(scene_image).resolve()),
            "mask_image": str(Path(mask_image).resolve()),
            "reference_image": str(Path(reference_image).resolve()),
            "seed": seed_val,
            "steps": steps,
            "guidance": guidance,
            "denoise": denoise,
            "lenovo_strength": lenovo_strength,
            "mrpopo_strength": mrpopo_strength,
            "mask_channel": mask_channel,
            "mask_expand": mask_expand,
            "mask_feather": mask_feather,
            "outputs": [str(p) for p in saved],
        }
        if saved:
            (out_root / f"{saved[0].stem}_meta.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )
        return saved
