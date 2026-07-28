# Photoreal AI App

Hybrid generative AI studio: pluggable pipelines, ComfyUI runtime, CLI / API / web.

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
pip install -r runtime/comfyui/requirements.txt
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

```bash
pip install -e ".[vlm]"
python scripts/download_models.py --vlm

photoreal vlm -p "Describe this." --images shot.png
photoreal reprompt -p "woman in a cafe"          # prints rewritten prompt
photoreal reprompt -p "studio portrait" --gen    # then photoreal_gen (Comfy up)
```

## Repo layout

| Path | Role |
|------|------|
| `photoreal/` | Package (pipelines, services, api, cli) |
| `runtime/` | Pinned ComfyUI + BFL flux2 |
| `data/` | Models / I/O |
| `scripts/download_models.py` | `--photoreal-gen`, `--vlm`, `--all`, … |
| `docs/` | Architecture + ability docs |

```bash
pip install -e ".[dev]" && pytest
```
