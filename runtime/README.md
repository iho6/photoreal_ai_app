# Runtime

Upstream engine trees live here **unmodified**. Product code under `photoreal/` talks to Comfy via HTTP — do not import or edit these trees for app features.

| Path | Upstream | Pinned commit |
|------|----------|---------------|
| `comfyui/` | https://github.com/comfyanonymous/ComfyUI | `e8f8c2ff432276f711604d21d1547686c2e89253` |
| `flux2/` | https://github.com/black-forest-labs/flux2 | `50fe5162777813d869182b139e83b10743caef15` |

## Rules

- Do **not** refactor, reformat, or reorganize files inside `comfyui/` or `flux2/`.
- Point models at this repo’s `data/models/` via the additive config [`../comfyui_extra_model_paths.yaml`](../comfyui_extra_model_paths.yaml) (Comfy: `--extra-model-paths-config`).
- To refresh from upstream: re-clone at a new SHA, update this table, leave application code alone.

## Start ComfyUI (photoreal_gen)

```bash
# from repo root, after models download
cd runtime/comfyui
python main.py --listen 127.0.0.1 --port 8188 --extra-model-paths-config ../../comfyui_extra_model_paths.yaml
```

See [docs/photoreal_gen.md](../docs/photoreal_gen.md) for install order and weights.
