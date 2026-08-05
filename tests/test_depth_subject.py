"""Unit tests for depth_subject helpers (no live Comfy)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from photoreal.pipelines.vision.depth_subject import (
    DEPTH_WORKFLOW,
    composite_depth_with_mask,
    patch_da3_workflow,
)
from photoreal.services.comfy_client import load_workflow_template


def test_patch_da3_workflow_sets_image_and_model():
    wf = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "x.png"}},
        "2": {
            "class_type": "LoadDA3Model",
            "inputs": {
                "model_name": "old.safetensors",
                "weight_dtype": "default",
            },
        },
        "3": {
            "class_type": "DA3Inference",
            "inputs": {"image": ["1", 0]},
        },
    }
    out = patch_da3_workflow(
        wf, image_ref="uploaded.png", model_name="depth_anything_3_mono_large.safetensors"
    )
    assert out["1"]["inputs"]["image"] == "uploaded.png"
    assert out["2"]["inputs"]["model_name"] == "depth_anything_3_mono_large.safetensors"
    assert wf["1"]["inputs"]["image"] == "x.png"  # deepcopy


def test_patch_da3_workflow_rewrites_legacy_da3_render_keys():
    wf = {
        "4": {
            "class_type": "DA3Render",
            "inputs": {
                "da3_geometry": ["3", 0],
                "output": "depth",
                "normalization": "min_max",
                "apply_sky_clip": True,
            },
        }
    }
    out = patch_da3_workflow(wf, image_ref="x.png")
    inp = out["4"]["inputs"]
    assert inp["output"] == "depth"
    assert inp["output.normalization"] == "min_max"
    assert inp["output.apply_sky_clip"] is True
    assert "normalization" not in inp
    assert "apply_sky_clip" not in inp


def test_depth_workflow_template_uses_dotted_da3_render_keys():
    wf = load_workflow_template(DEPTH_WORKFLOW)
    render = next(
        n for n in wf.values() if isinstance(n, dict) and n.get("class_type") == "DA3Render"
    )
    inp = render["inputs"]
    assert "output.normalization" in inp
    assert "output.apply_sky_clip" in inp
    assert "normalization" not in inp
    assert "apply_sky_clip" not in inp
    patched = patch_da3_workflow(wf, image_ref="frame.png")
    pin = next(
        n
        for n in patched.values()
        if isinstance(n, dict) and n.get("class_type") == "DA3Render"
    )["inputs"]
    assert pin["output.normalization"] == "v2_style"
    assert pin["output.apply_sky_clip"] is False


def test_composite_depth_with_mask_feathers(tmp_path: Path):
    depth = Image.new("RGB", (64, 64), (40, 40, 40))
    # Person blob on left half
    for x in range(0, 32):
        for y in range(64):
            depth.putpixel((x, y), (200, 200, 200))
    depth_path = tmp_path / "depth.png"
    depth.save(depth_path)

    mask = Image.new("L", (64, 64), 0)
    for x in range(0, 32):
        for y in range(64):
            mask.putpixel((x, y), 255)
    mask_path = tmp_path / "mask.png"
    mask.save(mask_path)

    out_path = tmp_path / "out.png"
    composite_depth_with_mask(
        depth_path, mask_path, out_path=out_path, feather_px=5
    )
    assert out_path.is_file()
    result = Image.open(out_path).convert("RGB")
    # Far right should be near white far-plane
    r, g, b = result.getpixel((60, 32))
    assert r > 240 and g > 240 and b > 240
    # Left interior keeps brighter depth
    r2, g2, b2 = result.getpixel((8, 32))
    assert r2 > 150


def test_depth_subject_validate_requires_files(tmp_path: Path):
    from photoreal.pipelines.vision.depth_subject import DepthSubjectPipeline

    pipe = DepthSubjectPipeline()
    with pytest.raises(ValueError, match="image"):
        pipe.validate(image=None, mask=tmp_path / "m.png")
    img = tmp_path / "i.png"
    Image.new("RGB", (8, 8), (0, 0, 0)).save(img)
    with pytest.raises(ValueError, match="mask"):
        pipe.validate(image=img, mask=tmp_path / "missing.png")
