# Photoreal AI App

Hybrid generative AI studio: pluggable pipelines, ComfyUI runtime, CLI / API / web.

## First run (launch portal)

Creates `.venv`, opens a white credential portal, then **Launch** installs weights and starts API + Comfy. Details: [docs/portal.md](docs/portal.md).

```bash
# Linux (primary / GPU) — needs tmux
chmod +x launch.sh scripts/launch.sh
./launch.sh
# tmux attach -t photoreal

# Windows
launch.bat
```

Portal: `http://127.0.0.1:8010/` — HF token + Runpod API key → **Launch**.

## `photoreal_gen`

Text-to-image on **FLUX.2 Klein 9B Base** with Lenovo UltraReal + Mrpopo photoreal LoRAs (ComfyUI). Same backbone can cover edit later. HF weights are **non-commercial** (gated). Details: [docs/photoreal_gen.md](docs/photoreal_gen.md).

**Structure**

| Piece | Path |
|-------|------|
| Pipeline | `photoreal/pipelines/image/photoreal_gen.py` |
| Comfy workflow | `photoreal/pipelines/image/workflows/photoreal_gen_api.json` |
| Comfy client | `photoreal/services/comfy_client.py` |
| Weights | `data/models/flux2/klein-base-9b/`, `data/models/loras/` |
| Engines | `runtime/comfyui`, `runtime/flux2` (upstream, unmodified) |

**Setup + CLI**

```bash
pip install -e ".[photoreal-gen]"
pip install -r requirements/comfyui-photoreal.txt
# HF_TOKEN after accepting FLUX NC on Hugging Face
python scripts/download_models.py --photoreal-gen   # or --all

# terminal 1 — ComfyUI
cd runtime/comfyui
python main.py --listen 127.0.0.1 --port 8188 --extra-model-paths-config ../../comfyui_extra_model_paths.local.yaml

# terminal 2
photoreal gen -p "hyper-detailed studio portrait, soft window light, 85mm"
```

Outputs: `data/outputs/photoreal_gen/`. Useful flags: `--width`, `--height`, `--seed`, `--steps`, `--guidance`, `--with-snofs`.

## `vlm` / `reprompt`

**Qwen3-VL-8B-Instruct** for multimodal Q&A and Popo-style photoreal prompt rewrite (run **sequentially** vs Klein on 24 GB). Details: [docs/vlm.md](docs/vlm.md).

**Structure**

| Piece | Path |
|-------|------|
| Engine | `photoreal/services/vlm_engine.py` (official HF Transformers API) |
| Ability `vlm` | `photoreal/pipelines/vision/vlm.py` |
| Ability `reprompt` | `photoreal/pipelines/vision/reprompt.py` |
| Popo few-shots | `photoreal/pipelines/vision/prompts/popo_photoreal_reprompt.json` |
| Weights | `data/models/vlm/Qwen3-VL-8B-Instruct` |

`reprompt` loads that JSON and builds a **text chat** for Qwen (system + user/assistant exemplar pairs + your `-p` idea). It is not uploaded as a raw file; the model never sees images unless you use `vlm --images` / `--video`.

```bash
pip install -e ".[vlm]"
python scripts/download_models.py --vlm

photoreal vlm -p "Describe this." --images shot.png
photoreal reprompt -p "woman in a cafe"          # prints rewritten prompt
photoreal reprompt -p "studio portrait" --gen    # unload VLM, then photoreal_gen (Comfy up)
```

## `sam3_segment`

**SAM 3.1** image segmentation (text and/or points) via ComfyUI’s native `SAM3_Detect` — not a direct Meta git import. Details: [docs/sam3_segment.md](docs/sam3_segment.md).

```bash
python scripts/download_models.py --sam3
# Comfy running with comfyui_extra_model_paths.yaml
photoreal sam3 -i shot.png -p "person" --job image_mask
photoreal sam3 -i shot.png --positive-coords '[{"x":100,"y":200}]' --job image_rgba
```

Portal: `POST /api/sam3/segment` (multipart), poll `GET /api/sam3/jobs/{id}`. Outputs: `data/outputs/sam3_segment/`.

## `depth_subject`

Person-only depth still (Depth Anything 3 + SAM mask, feathered backdrop). Timeline: Segment → Convert Depth → Show Depth. Details: [docs/depth_subject.md](docs/depth_subject.md).

```bash
python scripts/download_models.py --depth
```

Portal: `POST /api/depth/convert` (multipart image + mask), poll `GET /api/depth/jobs/{id}`. Outputs: `data/outputs/depth_subject/`.

## `character_depth`

Depth map + character reference → Klein render via RefControl depth LoRA. CLI only (not timeline-wired yet). Details: [docs/character_depth.md](docs/character_depth.md).

```bash
python scripts/download_models.py --photoreal-gen   # once
python scripts/download_models.py --character-depth
photoreal character-depth --depth depth.png --reference char.png -p "refcontrol"
```

## `character_inpaint`

Scene plate + person mask + character reference → scene-lit character bake (Klein masked edit). CLI only; lighting step before later Replace Character. Details: [docs/character_inpaint.md](docs/character_inpaint.md).

```bash
python scripts/download_models.py --photoreal-gen   # once
photoreal character-inpaint --scene plate.png --mask mask.png --reference char.png
```

## Replace Character (timeline)

Right-click clip/preview: **Segment** → **Depth** → **Character Reference** (gallery hover → inpaint) → **Pose Lock** (depth RefControl). Details: [docs/replace_character.md](docs/replace_character.md).

## Repo layout

| Path | Role |
|------|------|
| `photoreal/` | Package (pipelines, services, api, cli, portal) |
| `web/portal`, `web/ui` | Launch portal + shared white UI kit |
| `launch.sh` / `launch.bat` | Stage-1 entry (Linux / Windows) |
| `runtime/` | Pinned ComfyUI + BFL flux2 |
| `data/` | Models / I/O / logs |
| `scripts/download_models.py` | `--photoreal-gen`, `--vlm`, `--sam3`, `--depth`, `--character-depth`, `--all`, … |
| `docs/` | Architecture + ability docs |

```bash
pip install -e ".[dev]" && pytest
```
