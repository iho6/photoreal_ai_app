# `sam3_segment`

Image segmentation with **SAM 3.1** (multiplex) through **ComfyUI’s native** `SAM3_Detect` nodes — same approach as [ai-anime-2026](https://github.com/iho6/ai-anime-2026) `sam3_segment_ai_service`. This is **not** a direct import of Meta’s `facebookresearch/sam3` Python package.

## What it does

| Job | Output |
|-----|--------|
| `image_mask` | Mask PNG (`MaskToImage`) |
| `image_rgba` | RGBA cutout PNG |

Prompts: **text concept** and/or **positive/negative points** (`{"x","y"}`). At least one of text or a positive point is required.

Video tracking and Flash packaging are out of scope for v1.

## Structure

| Piece | Path |
|-------|------|
| Pipeline | `photoreal/pipelines/vision/sam3_segment.py` |
| Workflows | `photoreal/pipelines/vision/workflows/sam3_image_mask_api.json`, `sam3_image_rgba_api.json` |
| Checkpoint | `data/models/sam3/sam3.1_multiplex_fp16.safetensors` |
| Extra paths | `comfyui_extra_model_paths.yaml` → `photoreal_sam3` |
| Portal API | `POST /api/sam3/segment`, `GET /api/sam3/jobs/{id}` (includes `frame_url`, `cutout_url`) |
| Outputs | `data/outputs/sam3_segment/` (served at `/sam3-outputs/`) |

Weights come from Hugging Face `Comfy-Org/sam3.1` (accept terms / use `HF_TOKEN` if gated).

## Setup

```bash
# Comfy must already run with extra-model-paths (see photoreal_gen docs)
python scripts/download_models.py --sam3

photoreal sam3 -i shot.png -p "person" --job image_mask
photoreal sam3 -i shot.png --positive-coords '[{"x":120,"y":200}]' --job image_rgba
```

## Portal API (multipart)

```bash
curl -s -X POST http://127.0.0.1:8010/api/sam3/segment \
  -F image=@shot.png \
  -F job=image_mask \
  -F text_prompt=person
# → { "job_id": "...", "status": "running", ... }

curl -s http://127.0.0.1:8010/api/sam3/jobs/<job_id>
# → images: ["/sam3-outputs/....png"] when done
```

## Notes

- Restart Comfy after the first `--sam3` download so it picks up `data/models/sam3/`.
- Same VRAM caveats as other Comfy jobs: don’t run heavy Klein + SAM3 simultaneously on 24 GB without unloading.
- **Timeline Segment** always sends `text_prompt=person` (no concept dialog). Prefer short nouns over long prose if you call the API yourself.
- Job status payloads include a `logs` array; the Timeline operation-log modal streams those lines while the job runs.
