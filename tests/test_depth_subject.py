"""Unit tests for depth_subject helpers (no live Comfy)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from photoreal.pipelines.vision.depth_subject import (
    composite_depth_with_mask,
    patch_da3_workflow,
)


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
