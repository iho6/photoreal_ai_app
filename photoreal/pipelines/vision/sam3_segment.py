"""sam3_segment — SAM 3.1 image segmentation via ComfyUI SAM3_Detect."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from photoreal.config import get_settings
from photoreal.pipelines.base import Pipeline
from photoreal.services.comfy_client import ComfyClient, ComfyClientError, load_workflow_template

WORKFLOWS_DIR = Path(__file__).resolve().parent / "workflows"
MASK_WORKFLOW = WORKFLOWS_DIR / "sam3_image_mask_api.json"
RGBA_WORKFLOW = WORKFLOWS_DIR / "sam3_image_rgba_api.json"

JOB_MASK = "image_mask"
JOB_RGBA = "image_rgba"
VALID_JOBS = (JOB_MASK, JOB_RGBA)


def normalize_text_prompt(raw: str | None) -> str:
    return (raw or "").strip()


def coords_to_json(coords: list[dict[str, Any]] | None) -> str:
    out: list[dict[str, int]] = []
    for pt in coords or []:
        if not isinstance(pt, dict) or "x" not in pt or "y" not in pt:
            continue
        try:
            x = int(pt["x"])
            y = int(pt["y"])
        except (TypeError, ValueError):
            continue
        out.append({"x": x, "y": y})
    return json.dumps(out)


def validate_sam3_prompts(
    positive_coords: list[Any] | None,
    text_prompt: str | None,
) -> None:
    pos = positive_coords if isinstance(positive_coords, list) else []
    text = normalize_text_prompt(text_prompt)
    if not pos and not text:
        raise ValueError("Provide at least one positive point or a text prompt.")


def patch_sam3_workflow(
    workflow: dict[str, Any],
    *,
    image_ref: str,
    positive_coords: str,
    negative_coords: str,
    text_prompt: str = "",
    threshold: float | None = None,
    refine_iterations: int | None = None,
) -> dict[str, Any]:
    """Patch LoadImage / CLIPTextEncode / SAM3_Detect inputs (API-format graph)."""
    w = copy.deepcopy(workflow)
    for node in w.values():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type")
        inp = node.setdefault("inputs", {})
        if ct == "LoadImage":
            inp["image"] = image_ref
        elif ct == "CLIPTextEncode":
            inp["text"] = text_prompt
        elif ct == "SAM3_Detect":
            inp["positive_coords"] = positive_coords
            inp["negative_coords"] = negative_coords
            if threshold is not None:
                inp["threshold"] = float(threshold)
            if refine_iterations is not None:
                inp["refine_iterations"] = int(refine_iterations)
    return w


class Sam3SegmentPipeline(Pipeline):
    """Point- and/or text-prompt image segmentation via Comfy SAM3_Detect."""

    id = "sam3_segment"
    domain = "vision"

    def validate(
        self,
        *,
        image: str | Path | None = None,
        job: str = JOB_MASK,
        positive_coords: list[Any] | None = None,
        text_prompt: str | None = None,
        **kwargs: Any,
    ) -> None:
        if not image or not Path(image).is_file():
            raise ValueError("image is required and must be an existing file")
        job_id = (job or JOB_MASK).strip().lower()
        if job_id not in VALID_JOBS:
            raise ValueError(f"job must be one of {VALID_JOBS}, got {job!r}")
        if positive_coords is not None and not isinstance(positive_coords, list):
            raise ValueError("positive_coords must be a list when provided")
        neg = kwargs.get("negative_coords")
        if neg is not None and not isinstance(neg, list):
            raise ValueError("negative_coords must be a list when provided")
        validate_sam3_prompts(positive_coords, text_prompt)

    def run(
        self,
        *,
        image: str | Path,
        job: str = JOB_MASK,
        positive_coords: list[dict[str, Any]] | None = None,
        negative_coords: list[dict[str, Any]] | None = None,
        text_prompt: str = "",
        threshold: float = 0.5,
        refine_iterations: int = 2,
        comfy_url: str | None = None,
        output_dir: str | Path | None = None,
        **kwargs: Any,
    ) -> list[Path]:
        """
        Run SAM3 against a live ComfyUI server.

        Returns paths to saved PNGs under data/outputs/sam3_segment/.
        """
        self.validate(
            image=image,
            job=job,
            positive_coords=positive_coords,
            negative_coords=negative_coords,
            text_prompt=text_prompt,
        )
        job_id = (job or JOB_MASK).strip().lower()
        text = normalize_text_prompt(text_prompt)
        pos_json = coords_to_json(positive_coords)
        neg_json = coords_to_json(negative_coords)

        settings = get_settings()
        base = comfy_url or getattr(settings, "comfy_url", "http://127.0.0.1:8188")
        client = ComfyClient(base_url=base)

        if not client.health():
            raise ComfyClientError(
                f"ComfyUI not reachable at {base}. Start it with:\n"
                "  cd runtime/comfyui && python main.py --listen 127.0.0.1 --port 8188 "
                "--extra-model-paths-config ../../comfyui_extra_model_paths.yaml"
            )

        wf_path = RGBA_WORKFLOW if job_id == JOB_RGBA else MASK_WORKFLOW
        wf = load_workflow_template(wf_path)
        prompt_graph = {
            k: v for k, v in wf.items() if k != "_meta" and isinstance(v, dict)
        }

        image_ref = client.upload_image(image)
        prompt_graph = patch_sam3_workflow(
            prompt_graph,
            image_ref=image_ref,
            positive_coords=pos_json,
            negative_coords=neg_json,
            text_prompt=text,
            threshold=float(threshold),
            refine_iterations=int(refine_iterations),
        )

        out_root = (
            Path(output_dir)
            if output_dir
            else Path(settings.data_root) / "outputs" / "sam3_segment"
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
            "job": job_id,
            "image": str(Path(image).resolve()),
            "text_prompt": text,
            "positive_coords": json.loads(pos_json),
            "negative_coords": json.loads(neg_json),
            "threshold": float(threshold),
            "refine_iterations": int(refine_iterations),
            "outputs": [str(p) for p in saved],
        }
        (out_root / f"{saved[0].stem}_meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        return saved
