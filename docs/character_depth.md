# `character_depth`

Depth-to-character generation on **FLUX.2 Klein 9B Base** using the
[RefControl depth LoRA](https://huggingface.co/thedeoxen/refcontrol-FLUX.2-klein-9B-reference-depth-lora).

Takes a **person-only depth map** + a **character reference image**, preserves
identity from the reference, and follows pose/structure from the depth map.

**Not wired to the timeline UI yet** — Python / CLI only.

## Inputs

| Input | Role |
|-------|------|
| Depth PNG | Structure (prefer `depth_subject` output — backdrop already removed) |
| Character reference | Identity (Create Character white-studio sheet works well) |
| Prompt | Include or auto-inject trigger `refcontrol` |

## Setup

```bash
# 1) Klein Base + Lenovo + Mrpopo (if not already present)
python scripts/download_models.py --photoreal-gen

# 2) RefControl depth LoRA only
python scripts/download_models.py --character-depth

# Comfy must run with extra-model-paths (same as photoreal_gen)
```

Uses the existing `photoreal-gen` pip extra (`huggingface_hub`, `httpx`, …). No new Python package required.

## Structure

| Piece | Path |
|-------|------|
| Pipeline | `photoreal/pipelines/image/character_depth.py` |
| Workflow | `photoreal/pipelines/image/workflows/character_depth_api.json` |
| LoRA | `data/models/loras/flux2_klein_9b_refcontrol_depth.safetensors` |
| Outputs | `data/outputs/character_depth/` |

Comfy stack: Klein + Lenovo + Mrpopo + RefControl depth; dual `ReferenceLatent` (depth first, character second).

## CLI

```bash
photoreal character-depth \
  --depth data/outputs/depth_subject/frame_depth_subject.png \
  --reference path/to/character.png \
  -p "refcontrol, soft studio light" \
  --refcontrol-strength 0.9
```

## Tips

- Keep depth framing/scale close to the character reference.
- Default RefControl strength ~0.8–1.0 per the model card.
- Timeline **Pose Lock** uses this pipeline with the inpaint bake as reference (see [replace_character.md](replace_character.md)).
