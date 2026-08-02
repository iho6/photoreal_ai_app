"""Unit tests for character_inpaint helpers (no live Comfy)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from photoreal.pipelines.image.character_inpaint import (
    DEFAULT_PROMPT,
    CharacterInpaintPipeline,
    patch_character_inpaint_workflow,
)


def test_patch_character_inpaint_workflow():
    wf = {
        "4": {"inputs": {"strength_model": 0.1, "strength_clip": 0.1}},
        "5": {"inputs": {"strength_model": 0.1, "strength_clip": 0.1}},
        "6": {"inputs": {"text": "old"}},
        "8": {"inputs": {"guidance": 1.0}},
        "20": {"inputs": {"image": "a.png"}},
        "21": {"inputs": {"image": "b.png"}},
        "22": {"inputs": {"image": "c.png", "channel": "alpha"}},
        "23": {"inputs": {"expand": 0, "tapered_corners": True}},
        "24": {
            "inputs": {"left": 0, "top": 0, "right": 0, "bottom": 0},
        },
        "30": {"inputs": {"seed": 1, "steps": 4, "denoise": 0.5}},
    }
    out = patch_character_inpaint_workflow(
        wf,
        scene_ref="scene_up.png",
        mask_ref="mask_up.png",
        reference_ref="char_up.png",
        prompt="match lighting",
        seed=42,
        steps=28,
        guidance=4.0,
        denoise=0.95,
        lenovo_strength=0.85,
        mrpopo_strength=1.0,
        mask_channel="red",
        mask_expand=6,
        mask_feather=8,
    )
    assert out["20"]["inputs"]["image"] == "scene_up.png"
    assert out["21"]["inputs"]["image"] == "char_up.png"
    assert out["22"]["inputs"]["image"] == "mask_up.png"
    assert out["22"]["inputs"]["channel"] == "red"
    assert out["6"]["inputs"]["text"] == "match lighting"
    assert out["30"]["inputs"]["seed"] == 42
    assert out["30"]["inputs"]["denoise"] == 0.95
    assert out["23"]["inputs"]["expand"] == 6
    assert out["24"]["inputs"]["left"] == 8
    assert wf["20"]["inputs"]["image"] == "a.png"  # deepcopy


def test_patch_empty_prompt_uses_default():
    wf = {
        "4": {"inputs": {"strength_model": 0.1, "strength_clip": 0.1}},
        "5": {"inputs": {"strength_model": 0.1, "strength_clip": 0.1}},
        "6": {"inputs": {"text": "old"}},
        "8": {"inputs": {"guidance": 1.0}},
        "20": {"inputs": {"image": "a.png"}},
        "21": {"inputs": {"image": "b.png"}},
        "22": {"inputs": {"image": "c.png", "channel": "red"}},
        "23": {"inputs": {"expand": 0, "tapered_corners": True}},
        "24": {
            "inputs": {"left": 0, "top": 0, "right": 0, "bottom": 0},
        },
        "30": {"inputs": {"seed": 1, "steps": 4, "denoise": 0.5}},
    }
    out = patch_character_inpaint_workflow(
        wf,
        scene_ref="s.png",
        mask_ref="m.png",
        reference_ref="r.png",
        prompt="  ",
        seed=1,
        steps=10,
        guidance=4.0,
        denoise=0.9,
        lenovo_strength=0.8,
        mrpopo_strength=1.0,
    )
    assert out["6"]["inputs"]["text"] == DEFAULT_PROMPT


def test_character_inpaint_validate(tmp_path: Path):
    pipe = CharacterInpaintPipeline()
    scene = tmp_path / "s.png"
    mask = tmp_path / "m.png"
    ref = tmp_path / "r.png"
    Image.new("RGB", (8, 8), (0, 0, 0)).save(scene)
    Image.new("L", (8, 8), 255).save(mask)
    Image.new("RGB", (8, 8), (1, 1, 1)).save(ref)

    with pytest.raises(ValueError, match="scene_image"):
        pipe.validate(
            scene_image=None, mask_image=mask, reference_image=ref
        )
    with pytest.raises(ValueError, match="mask_image"):
        pipe.validate(
            scene_image=scene,
            mask_image=tmp_path / "missing.png",
            reference_image=ref,
        )
    with pytest.raises(ValueError, match="reference_image"):
        pipe.validate(
            scene_image=scene, mask_image=mask, reference_image=None
        )
    pipe.validate(
        scene_image=scene, mask_image=mask, reference_image=ref, prompt="ok"
    )
