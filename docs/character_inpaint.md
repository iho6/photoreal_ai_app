# `character_inpaint`

Place a **character reference** into a **masked person region** of a scene plate
on **FLUX.2 Klein 9B Base** (Lenovo + Mrpopo). Produces a **scene-lit character
bake** — lighting/context from the plate, identity from the reference.

This is the lighting step intended **before** Pose Lock
(`character_depth` / RefControl).

On the **timeline**, Character Reference builds the scene client-side:
overlapping **backdrop** (cover-scaled) + segmented **cutout**, then POSTs that
composite as `scene` (not the raw reference plate). See [replace_character.md](replace_character.md).

## Inputs

| Input | Role |
|-------|------|
| Scene plate | Environment + lighting (CLI: any plate; timeline: cutout-on-backdrop composite) |
| Person mask | Region to replace (e.g. SAM3 segment) |
| Character reference | Identity (Create Character white-studio sheet) |
| Prompt | Edit instruction (default: match lighting / replace person) |

## Setup

```bash
# Klein Base + Lenovo + Mrpopo (no extra inpaint checkpoint)
python scripts/download_models.py --photoreal-gen

# Comfy must run with extra-model-paths (same as photoreal_gen)
```

Uses the existing `photoreal-gen` pip extra. No new model download for this ability.

## Structure

| Piece | Path |
|-------|------|
| Pipeline | `photoreal/pipelines/image/character_inpaint.py` |
| Workflow | `photoreal/pipelines/image/workflows/character_inpaint_api.json` |
| Outputs | `data/outputs/character_inpaint/` |

Comfy stack: Klein + Lenovo + Mrpopo; dual `ReferenceLatent` (scene then character);
`LoadImageMask` → Grow/Feather → `SetLatentNoiseMask` on scene latents.

## CLI

```bash
photoreal character-inpaint \
  --scene path/to/plate.png \
  --mask path/to/person_mask.png \
  --reference path/to/character.png \
  -p "replace the person with the reference character, match scene lighting" \
  --denoise 0.95
```

## Tips

- Grayscale SAM masks: `--mask-channel red` (default). RGBA alpha masks: `alpha`.
- Soften edges with `--mask-expand` / `--mask-feather` if seams show.
- Output bake can later feed `character_depth` as the lighting-matched reference.
- Timeline: require an overlapping **Create Location** plate (`role=location`); scene lighting comes from that backdrop. Untagged image/video clips are ignored.
