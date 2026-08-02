"""Unit tests for sam3_segment prompts / workflow patching (no GPU)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from photoreal.pipelines.vision.sam3_segment import (
    JOB_MASK,
    MASK_WORKFLOW,
    RGBA_WORKFLOW,
    coords_to_json,
    normalize_text_prompt,
    patch_sam3_workflow,
    validate_sam3_prompts,
)
from photoreal.services.comfy_client import load_workflow_template


def test_workflow_templates_exist_and_load() -> None:
    assert MASK_WORKFLOW.is_file()
    assert RGBA_WORKFLOW.is_file()
    mask = load_workflow_template(MASK_WORKFLOW)
    rgba = load_workflow_template(RGBA_WORKFLOW)
    assert any(n.get("class_type") == "SAM3_Detect" for n in mask.values() if isinstance(n, dict))
    assert any(n.get("class_type") == "SAM3_Detect" for n in rgba.values() if isinstance(n, dict))
    assert any(n.get("class_type") == "JoinImageWithAlpha" for n in rgba.values() if isinstance(n, dict))


def test_validate_requires_text_or_points() -> None:
    with pytest.raises(ValueError, match="positive point or a text prompt"):
        validate_sam3_prompts([], "")
    validate_sam3_prompts([], "person")
    validate_sam3_prompts([{"x": 1, "y": 2}], "")


def test_coords_to_json_filters_bad_entries() -> None:
    raw = [{"x": 10, "y": 20}, "nope", {"x": "3", "y": 4.2}, {"z": 1}]
    assert json.loads(coords_to_json(raw)) == [{"x": 10, "y": 20}, {"x": 3, "y": 4}]
    assert coords_to_json(None) == "[]"


def test_patch_sam3_workflow_sets_inputs() -> None:
    wf = load_workflow_template(MASK_WORKFLOW)
    patched = patch_sam3_workflow(
        wf,
        image_ref="photoreal_sam3_inputs/in.png",
        positive_coords='[{"x":1,"y":2}]',
        negative_coords="[]",
        text_prompt="red car",
        threshold=0.7,
        refine_iterations=3,
    )
    load = next(n for n in patched.values() if n.get("class_type") == "LoadImage")
    clip = next(n for n in patched.values() if n.get("class_type") == "CLIPTextEncode")
    det = next(n for n in patched.values() if n.get("class_type") == "SAM3_Detect")
    assert load["inputs"]["image"] == "photoreal_sam3_inputs/in.png"
    assert clip["inputs"]["text"] == "red car"
    assert det["inputs"]["positive_coords"] == '[{"x":1,"y":2}]'
    assert det["inputs"]["threshold"] == 0.7
    assert det["inputs"]["refine_iterations"] == 3
    # original template unchanged
    orig_det = next(n for n in wf.values() if n.get("class_type") == "SAM3_Detect")
    assert orig_det["inputs"]["threshold"] == 0.5


def test_pipeline_validate_image_required(tmp_path: Path) -> None:
    from photoreal.pipelines.vision.sam3_segment import Sam3SegmentPipeline

    pipe = Sam3SegmentPipeline()
    with pytest.raises(ValueError, match="image is required"):
        pipe.validate(image=tmp_path / "missing.png", text_prompt="a")
    img = tmp_path / "ok.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    pipe.validate(image=img, job=JOB_MASK, text_prompt="a")
    assert normalize_text_prompt("  hi ") == "hi"


def test_download_models_registers_sam3() -> None:
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "download_models.py"
    spec = importlib.util.spec_from_file_location("download_models_sam3", script)
    assert spec and spec.loader
    dm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dm)
    assert "sam3" in dm.ABILITIES
    assert "sam3" in dm.ABILITY_DOWNLOADERS
    parser = dm.build_parser()
    args = parser.parse_args(["--sam3"])
    assert dm.selected_abilities(args) == ["sam3"]
