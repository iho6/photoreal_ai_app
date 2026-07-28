# photoreal_gen

Single image ability: **FLUX.2 Klein 9B Base** + **Lenovo UltraReal** + **Mrpopo photoreal** via unmodified ComfyUI.

## License

- Klein 9B Base / AE: **FLUX Non-Commercial** (Hugging Face gated). Accept the license on the model pages and set `HF_TOKEN` before downloading.
- LoRAs: follow each Civitai page; they still sit on an NC base model.
- Default stack is SFW. SNOFS is optional NSFW (`--with-snofs`).

## Install order (one track — do not flatten upstream reqs)

```bash
# from repo root
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -e ".[photoreal-gen]"
pip install -r runtime/comfyui/requirements.txt
# Install PyTorch per ComfyUI / your CUDA docs if not already satisfied

# gated HF downloads + public Civitai LoRAs
set HF_TOKEN=hf_...          # Windows PowerShell: $env:HF_TOKEN="hf_..."
python scripts/download_models.py --photoreal-gen
# optional NSFW:
# python scripts/download_models.py --photoreal-gen --with-snofs
# all abilities:
# python scripts/download_models.py --all
```

Upstream trees (do not refactor):

| Path | Pin |
|------|-----|
| `runtime/comfyui` | `e8f8c2ff432276f711604d21d1547686c2e89253` |
| `runtime/flux2` | `50fe5162777813d869182b139e83b10743caef15` |

## Weights downloaded

| Asset | Where | Access |
|-------|-------|--------|
| `flux-2-klein-base-9b.safetensors` | `data/models/flux2/klein-base-9b/` | HF gated `FLUX.2-klein-base-9B` |
| `ae.safetensors` | same | HF gated `FLUX.2-dev` (**only** AE, not full dev) |
| text encoder / tokenizer | `.../text_encoder/`, `.../tokenizer/` | from Klein base repo |
| `qwen_3_8b.safetensors` | under `text_encoder/` | **Required for Comfy CLIPLoader** — provide a single-file Qwen3-8B (name must match workflow) |
| `lenovo_flux_klein9b.safetensors` | `data/models/loras/` | Civitai **2682771** public |
| `mrpopo_photorealistic.safetensors` | `data/models/loras/` | Civitai **2972219** public |
| `klein_snofs_v1_1.safetensors` | `data/models/loras/optional/` | Civitai **2695876** public, optional |

Manifest: `data/models/photoreal_gen_manifest.json` (written by `scripts/download_models.py --photoreal-gen`).

**Do not download:** Klein 4B, distilled 9B, 9B KV, full `flux2-dev.safetensors`, Mistral upsample.

## Weight access check (API)

- Lenovo / Mrpopo / SNOFS: **public** Civitai download URLs verified.
- Klein 9B Base + AE: metadata public, **files gated** — need HF login + license accept.

## Run ComfyUI

```bash
cd runtime/comfyui
python main.py --listen 127.0.0.1 --port 8188 --extra-model-paths-config ../../comfyui_extra_model_paths.local.yaml
```

If `.local.yaml` is missing, run the download script once (it generates absolute paths), or use [`comfyui_extra_model_paths.yaml`](../comfyui_extra_model_paths.yaml) with paths adjusted for your cwd.

## Run generation

```bash
photoreal gen --prompt "A hyper-detailed studio portrait, soft window light, 85mm photograph"
# or
python -m photoreal.cli.main gen -p "..."
```

Outputs: `data/outputs/photoreal_gen/`.

## Layout reminder

- App glue: `photoreal/pipelines/image/photoreal_gen.py` + Comfy API client.
- Workflow: `photoreal/pipelines/image/workflows/photoreal_gen_api.json`.
- Engines: `runtime/comfyui`, `runtime/flux2` — **original upstream copies**.
