"""Unit tests for character_depth helpers (no live Comfy)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from photoreal.pipelines.image.character_depth import (
    CharacterDepthPipeline,
    ensure_refcontrol_trigger,
    patch_character_depth_workflow,
)


def test_ensure_refcontrol_trigger_adds_token():
    assert ensure_refcontrol_trigger("") == "refcontrol"
    assert ensure_refcontrol_trigger("soft light") == "refcontrol soft light"
    assert ensure_refcontrol_trigger("refcontrol soft light").startswith("refcontrol")
    assert ensure_refcontrol_trigger("REFCONTROL soft").lower().startswith("refcontrol")


def test_patch_character_depth_workflow():
    wf = {
        "4": {"inputs": {"strength_model": 0.1, "strength_clip": 0.1}},
        "5": {"inputs": {"strength_model": 0.1, "strength_clip": 0.1}},
        "6": {
            "inputs": {
                "lora_name": "x.safetensors",
                "strength_model": 0.1,
                "strength_clip": 0.1,
            }
        },
        "7": {"inputs": {"text": "old"}},
        "9": {"inputs": {"guidance": 1.0}},
        "20": {"inputs": {"image": "a.png"}},
        "21": {"inputs": {"image": "b.png"}},
        "26": {"inputs": {"width": 512, "height": 512}},
        "27": {"inputs": {"seed": 1, "steps": 4}},
    }
    out = patch_character_depth_workflow(
        wf,
        depth_ref="depth_up.png",
        reference_ref="char_up.png",
        prompt="studio",
        width=1024,
        height=768,
        seed=42,
        steps=28,
        guidance=4.0,
        lenovo_strength=0.85,
        mrpopo_strength=1.0,
        refcontrol_strength=0.9,
    )
    assert out["20"]["inputs"]["image"] == "depth_up.png"
    assert out["21"]["inputs"]["image"] == "char_up.png"
    assert "refcontrol" in out["7"]["inputs"]["text"]
    assert out["27"]["inputs"]["seed"] == 42
    assert out["26"]["inputs"]["width"] == 1024
    assert out["6"]["inputs"]["strength_model"] == 0.9
    assert wf["20"]["inputs"]["image"] == "a.png"  # deepcopy


def test_character_depth_validate(tmp_path: Path):
    pipe = CharacterDepthPipeline()
    with pytest.raises(ValueError, match="depth_image"):
        pipe.validate(depth_image=None, reference_image=tmp_path / "r.png")
    depth = tmp_path / "d.png"
    Image.new("RGB", (8, 8), (0, 0, 0)).save(depth)
    with pytest.raises(ValueError, match="reference_image"):
        pipe.validate(depth_image=depth, reference_image=tmp_path / "missing.png")
    ref = tmp_path / "r.png"
    Image.new("RGB", (8, 8), (1, 1, 1)).save(ref)
    pipe.validate(depth_image=depth, reference_image=ref, prompt="refcontrol")
