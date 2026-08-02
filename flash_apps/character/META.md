# Flash app: `character`

| Field | Value |
|-------|--------|
| **App id** | `character` |
| **Endpoint name** | `photoreal-character-4090` |
| **GPU** | `GpuType.NVIDIA_GEFORCE_RTX_4090` |
| **Datacenter** | `US-CA-2` (`VOLUME_DATACENTER`) |
| **Network volume** | `photoreal-models` @ `/runpod-volume/` |
| **Worker** | `photoreal.flash.worker_character.character_generate_impl` |
| **Portal cache** | `.env` → `FLASH_CHARACTER_ENDPOINT` |
| **Status** | active |

Restart the **portal** after changing datacenter/volume code so sync uses `US-CA-2`. First model fill onto the volume can take hours.

## What it does

Create Character / portal Generate: VLM reprompt → `photoreal_gen` via Comfy on the volume.

## Deploy

```bash
bash scripts/flash_deploy_app.sh character
# or
bash scripts/flash_deploy_character.sh
```

Windows without WSL: portal Generate dispatches GitHub Actions `flash-deploy-app.yml` with `app=character`.

## Artifact notes

- Code staged from `MANIFEST.txt` only (no portal/web/runtime).
- Pip excludes: `flash_apps/_shared/excludes.txt` (torch + nvidia CUDA wheels).
- Deploy uses `--no-deps` by default so transformers does not pull CUDA wheels; endpoint `dependencies=` lists needed direct packages.
- Weights + ComfyUI: Network Volume only (see docs/portal.md).
