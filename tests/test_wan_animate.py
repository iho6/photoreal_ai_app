"""Unit tests for wan_animate helpers (no live Comfy / GPU)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from photoreal.pipelines.video.wan_animate import (
    WanAnimatePipeline,
    align_dim,
    clamp_wan_length,
    next_video_frame_offset,
    patch_wan_animate_workflow,
)


def test_align_dim():
    assert align_dim(832) == 832
    assert align_dim(833) == 832
    assert align_dim(8) == 16
    assert align_dim(480, 16) == 480


def test_clamp_wan_length():
    assert clamp_wan_length(77) == 77
    assert clamp_wan_length(100) == 77
    assert clamp_wan_length(77, remaining=40) == 37
    assert clamp_wan_length(77, remaining=2) == 1
    assert clamp_wan_length(77, remaining=0) == 0
    assert clamp_wan_length(10, remaining=100) == 9


def test_next_video_frame_offset():
    assert next_video_frame_offset(0, 77) == 77
    assert next_video_frame_offset(77, 37) == 114


def test_patch_wan_animate_workflow():
    wf = {
        "1": {"inputs": {"unet_name": "x.safetensors", "weight_dtype": "default"}},
        "5": {"inputs": {"lora_name": "y.safetensors", "strength_model": 0.5}},
        "6": {"inputs": {"shift": 1.0}},
        "7": {"inputs": {"text": "old"}},
        "8": {"inputs": {"text": "neg"}},
        "9": {"inputs": {"image": "a.png"}},
        "11": {"inputs": {"file": "b.mp4"}},
        "13": {
            "inputs": {
                "vitpose_model": "a.onnx",
                "yolo_model": "b.onnx",
                "onnx_device": "CPUExecutionProvider",
            }
        },
        "14": {"inputs": {"width": 64, "height": 64}},
        "15": {"inputs": {"width": 64, "height": 64}},
        "16": {
            "inputs": {
                "width": 64,
                "height": 64,
                "length": 9,
                "video_frame_offset": 0,
                "continue_motion_max_frames": 5,
            }
        },
        "18": {"inputs": {"seed": 1, "steps": 20, "cfg": 5.0}},
        "20": {"inputs": {"fps": 24.0}},
    }
    out = patch_wan_animate_workflow(
        wf,
        character_ref="up/char.png",
        video_ref="drive.mp4",
        prompt="walk",
        negative_prompt="bad",
        width=840,
        height=490,
        length=77,
        seed=42,
        steps=4,
        cfg=1.0,
        fps=24.0,
        lora_strength=1.0,
        shift=8.0,
        video_frame_offset=77,
        continue_motion_max_frames=5,
        continue_motion_ref="prev.mp4",
    )
    assert out["9"]["inputs"]["image"] == "up/char.png"
    assert out["11"]["inputs"]["file"] == "drive.mp4"
    assert out["7"]["inputs"]["text"] == "walk"
    assert out["16"]["inputs"]["width"] == 832
    assert out["16"]["inputs"]["height"] == 480
    assert out["16"]["inputs"]["length"] == 77
    assert out["16"]["inputs"]["video_frame_offset"] == 77
    assert out["16"]["inputs"]["continue_motion"] == ["24", 0]
    assert out["22"]["inputs"]["file"] == "prev.mp4"
    assert out["18"]["inputs"]["seed"] == 42
    assert out["20"]["inputs"]["fps"] == 24.0
    assert wf["9"]["inputs"]["image"] == "a.png"  # deepcopy

    out2 = patch_wan_animate_workflow(
        out,
        character_ref="up/char.png",
        video_ref="drive.mp4",
        prompt="walk",
        negative_prompt="bad",
        width=832,
        height=480,
        length=77,
        seed=1,
        steps=4,
        cfg=1.0,
        fps=24.0,
        lora_strength=1.0,
        shift=8.0,
        continue_motion_ref=None,
    )
    assert "continue_motion" not in out2["16"]["inputs"]
    assert "22" not in out2


def test_wan_animate_validate(tmp_path: Path):
    pipe = WanAnimatePipeline()
    with pytest.raises(ValueError, match="character_image"):
        pipe.validate(character_image=None, driving_video=tmp_path / "v.mp4")
    char = tmp_path / "c.png"
    Image.new("RGB", (8, 8), (0, 0, 0)).save(char)
    with pytest.raises(ValueError, match="driving_video"):
        pipe.validate(character_image=char, driving_video=tmp_path / "missing.mp4")
    vid = tmp_path / "v.mp4"
    vid.write_bytes(b"not-a-real-mp4")
    pipe.validate(character_image=char, driving_video=vid, prompt="hi")
    with pytest.raises(ValueError, match="continue_motion"):
        pipe.validate(
            character_image=char,
            driving_video=vid,
            continue_motion=tmp_path / "missing_prev.mp4",
        )


def test_download_models_registers_wan_animate() -> None:
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "download_models.py"
    spec = importlib.util.spec_from_file_location("download_models_wan", script)
    assert spec and spec.loader
    dm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dm)
    assert "wan_animate" in dm.ABILITIES
    assert "wan_animate" in dm.ABILITY_DOWNLOADERS
    assert dm.selected_abilities(
        dm.build_parser().parse_args(["--wan-animate"])
    ) == ["wan_animate"]
