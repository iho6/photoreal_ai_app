"""depth_subject — Depth Anything 3 + SAM mask composite (person-only depth)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from photoreal.config import get_settings
from photoreal.pipelines.base import Pipeline
from photoreal.services.comfy_client import ComfyClient, ComfyClientError, load_workflow_template

WORKFLOWS_DIR = Path(__file__).resolve().parent / "workflows"
DEPTH_WORKFLOW = WORKFLOWS_DIR / "da3_image_depth_api.json"
DEFAULT_MODEL = "depth_anything_3_mono_large.safetensors"
DEFAULT_FEATHER_PX = 7
FAR_PLANE = (255, 255, 255)


def patch_da3_workflow(
    workflow: dict[str, Any],
    *,
    image_ref: str,
    model_name: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    w = copy.deepcopy(workflow)
    for node in w.values():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type")
        inp = node.setdefault("inputs", {})
        if ct == "LoadImage":
            inp["image"] = image_ref
        elif ct == "LoadDA3Model":
            inp["model_name"] = model_name
    return w


def composite_depth_with_mask(
    depth_path: Path,
    mask_path: Path,
    *,
    out_path: Path,
    feather_px: int = DEFAULT_FEATHER_PX,
    far_rgb: tuple[int, int, int] = FAR_PLANE,
) -> Path:
    """Keep depth inside feathered mask; fill outside with far-plane white."""
    from PIL import Image, ImageFilter

    depth = Image.open(depth_path).convert("RGB")
    mask = Image.open(mask_path)
    if mask.mode not in ("L", "1"):
        # SAM MaskToImage is usually RGB grayscale
        mask = mask.convert("L")
    else:
        mask = mask.convert("L")

    if mask.size != depth.size:
        mask = mask.resize(depth.size, Image.Resampling.BILINEAR)

    feather = max(0, int(feather_px))
    if feather > 0:
        # Odd radius looks smoother for GaussianBlur
        radius = feather if feather % 2 == 1 else feather + 1
        mask = mask.filter(ImageFilter.GaussianBlur(radius=radius))

    far = Image.new("RGB", depth.size, far_rgb)
    out = Image.composite(depth, far, mask)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path, format="PNG")
    return out_path


class DepthSubjectPipeline(Pipeline):
    """Run DA3 depth then mask-composite to a person-only depth still."""

    id = "depth_subject"
    domain = "vision"

    def validate(
        self,
        *,
        image: str | Path | None = None,
        mask: str | Path | None = None,
        **kwargs: Any,
    ) -> None:
        if not image or not Path(image).is_file():
            raise ValueError("image is required and must be an existing file")
        if not mask or not Path(mask).is_file():
            raise ValueError("mask is required and must be an existing file")

    def run(
        self,
        *,
        image: str | Path,
        mask: str | Path,
        feather_px: int = DEFAULT_FEATHER_PX,
        model_name: str = DEFAULT_MODEL,
        comfy_url: str | None = None,
        output_dir: str | Path | None = None,
        **kwargs: Any,
    ) -> list[Path]:
        self.validate(image=image, mask=mask)
        settings = get_settings()
        base = comfy_url or getattr(settings, "comfy_url", "http://127.0.0.1:8188")
        client = ComfyClient(base_url=base)

        if not client.health():
            raise ComfyClientError(
                f"ComfyUI not reachable at {base}. Start it with:\n"
                "  cd runtime/comfyui && python main.py --listen 127.0.0.1 --port 8188 "
                "--extra-model-paths-config ../../comfyui_extra_model_paths.yaml"
            )

        wf = load_workflow_template(DEPTH_WORKFLOW)
        prompt_graph = {
            k: v for k, v in wf.items() if k != "_meta" and isinstance(v, dict)
        }
        image_ref = client.upload_image(
            image, subfolder="photoreal_depth_inputs"
        )
        prompt_graph = patch_da3_workflow(
            prompt_graph, image_ref=image_ref, model_name=model_name
        )

        out_root = (
            Path(output_dir)
            if output_dir
            else Path(settings.data_root) / "outputs" / "depth_subject"
        )
        out_root.mkdir(parents=True, exist_ok=True)

        raw_images = client.run_workflow(prompt_graph)
        if not raw_images:
            raise ComfyClientError("DA3 workflow returned no images")

        raw_name, raw_bytes = raw_images[0]
        raw_path = out_root / f"_raw_{Path(raw_name).name}"
        raw_path.write_bytes(raw_bytes)

        stem = Path(image).stem
        final_path = out_root / f"{stem}_depth_subject.png"
        composite_depth_with_mask(
            raw_path,
            Path(mask),
            out_path=final_path,
            feather_px=int(feather_px),
        )

        meta = {
            "pipeline": self.id,
            "image": str(Path(image).resolve()),
            "mask": str(Path(mask).resolve()),
            "feather_px": int(feather_px),
            "model_name": model_name,
            "raw_depth": str(raw_path),
            "output": str(final_path),
        }
        (out_root / f"{final_path.stem}_meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        return [final_path]
