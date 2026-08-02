# `depth_subject`

Person-only depth stills via **Depth Anything 3** (Comfy native) + a **SAM3 mask** with soft-feathered backdrop removal. Used by timeline **Convert Depth** after **Segment**.

## What it does

1. Runs DA3 on the segmented frame → greyscale depth visualization  
2. Feather-blurs the SAM mask (~7px)  
3. Composites: keep depth inside the person, fill outside with far-plane white  

Output: `data/outputs/depth_subject/*_depth_subject.png` (served at `/depth-outputs/`).

## Structure

| Piece | Path |
|-------|------|
| Pipeline | `photoreal/pipelines/vision/depth_subject.py` |
| Workflow | `photoreal/pipelines/vision/workflows/da3_image_depth_api.json` |
| Checkpoint | `data/models/depth_anything3/depth_anything_3_mono_large.safetensors` |
| Extra paths | `comfyui_extra_model_paths.yaml` → `photoreal_depth` / `geometry_estimation` |
| Portal API | `POST /api/depth/convert`, `GET /api/depth/jobs/{id}` |
| Timeline | Clip menu: Segment → Convert Depth → Show Depth checkbox |

## Setup

```bash
# Comfy must already run with extra-model-paths
python scripts/download_models.py --depth

# Restart Comfy after first download so it sees geometry_estimation paths
```

## Portal API (multipart)

- `image` — RGB frame PNG (same frame that was segmented)  
- `mask` — SAM3 mask PNG  
- `feather_px` — optional, default `7`  

Poll `GET /api/depth/jobs/{job_id}` until `status` is `done`; `images[0]` is the depth still URL.

## Timeline UX

1. Right-click clip → **Segment** (stores `segmentMaskUrl` + `segmentFrameUrl` on the clip)  
2. **Convert Depth** enables after segment; runs DA3 + composite  
3. Menu row becomes **Show Depth** checkbox; when on, main preview shows the depth still (scrub to the ref clip start to inspect)
