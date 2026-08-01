# Launch portal

Cross-platform two-stage bootstrap for Photoreal.

## First run

**Linux (primary / GPU):**

```bash
chmod +x launch.sh scripts/launch.sh
./launch.sh
# requires tmux — sudo apt install tmux
# attach servers: tmux attach -t photoreal
```

**Windows:**

```bat
launch.bat
```

Opens `http://127.0.0.1:8010/` — enter **HF token** and **Runpod API key** (auto-saves), then **Launch**.

## Stages

1. **Stage 1 (script):** create `.venv`, `pip install -e ".[portal]"`, start API/portal on `:8010`, open browser.
2. **Stage 2 (Launch button):** write `.env`, install `.[photoreal-gen,vlm]` + curated Comfy deps (`requirements/comfyui-photoreal.txt`) **only if missing**, `download_models.py --all` (skips existing weights), then start **API + ComfyUI**. On success the browser opens the **timeline** studio at `/timeline`.

Relaunch / click **Launch** again: cancels any in-flight Stage-2 (kills the download subprocess) and starts fresh. Civitai `.partial` files resume via HTTP Range; Hugging Face resumes incomplete cache shards. Stale Comfy on `:8188` is stopped before restart; a healthy API on `:8010` is left running. Stage-1 skips `.[portal]` when already importable.


| Service | Port |
|---------|------|
| API + portal | `127.0.0.1:8010` |
| ComfyUI | `127.0.0.1:8188` |

**Linux:** tmux session `photoreal` (windows `api`, `comfy`).  
**Windows:** detached processes; logs under `data/logs/api.log` and `data/logs/comfy.log`.

## Credentials

Saved to `.env` (gitignored) **only via the portal login page** — do not rely on typing secrets in a terminal. Required before Launch:

| Field | Env key |
|-------|---------|
| Hugging Face token | `HF_TOKEN` |
| Runpod API key | `RUNPOD_API_KEY` |

Optional: GitHub token. Flash character endpoint id (`FLASH_CHARACTER_ENDPOINT`) is **auto-resolved** from the deployed name `photoreal-character-4090` and cached in `.env` after the first Generate. Never commit `.env`.

## Runpod Flash (character Generate)

Flash setup is **required** for Launch (portal Runpod API key). Flash CLI is **macOS/Linux only**. On Windows:

- **No WSL distro (recommended here):** Generate dispatches GitHub Actions (`.github/workflows/flash-deploy-character.yml`) when the endpoint is missing.
- **WSL2 + Ubuntu:** local `.\scripts\flash_deploy_character.ps1` as before.

The portal calls Runpod Serverless HTTP with the saved key after deploy.

Docs: [Flash overview](https://docs.runpod.io/flash/overview), [Windows WSL2](https://docs.runpod.io/flash/windows-wsl2).

### Windows: Flash deploy via GitHub Actions (no local Ubuntu)

One-time setup:

1. Push this repo to GitHub (workflow file must be on the branch you dispatch).
2. On the portal, save **Runpod API key**, **HF token**, and a **GitHub token** with classic `repo` scope (or fine-grained: **Actions** + **Secrets** + **Contents**).

Save or Launch **auto-pushes** Actions secrets `RUNPOD_API_KEY` and `HF_TOKEN` to the GitHub repo via API — you do not need to enter them under Settings → Secrets on the website (unless the token lacks Secrets permission).

Then **Generate** auto-deploys when `photoreal-character-4090` is missing. Manual: **Actions → Flash deploy character → Run workflow**.

### Windows: WSL distro (optional alternative)

```powershell
# elevated PowerShell
wsl --install -d Ubuntu
```

Reboot if prompted, open **Ubuntu** once, then `.\scripts\flash_deploy_character.ps1`.

### First-time character endpoint deploy

1. Save **Runpod API key** (and on Windows without WSL: **GitHub token**) on the portal.
2. Either:
   - Click **Generate** once — missing endpoint triggers Flash deploy (GHA on Windows without WSL, else local/WSL); **or**
   - Manually: Actions workflow / `.\scripts\flash_deploy_character.ps1` / `bash scripts/flash_deploy_character.sh`.
3. Network Volume models are **auto-synced on first Generate** when incomplete (see below); or run `python scripts/flash_sync_volume.py`.

### Smoke (RTX 4090)

```bash
# in WSL, from repo root
pip install runpod-flash
flash login                 # or rely on portal .env RUNPOD_API_KEY
flash deploy
python scripts/flash_smoke_4090.py
```

Success log must show a real `NVIDIA GeForce RTX 4090` string.

### Character endpoint (manual)

```powershell
# Windows (WSL)
.\scripts\flash_deploy_character.ps1
```

Portal resolves endpoint id by name `photoreal-character-4090` (API key only) and caches it in `.env`.

Portal routing (`GENERATE_BACKEND`):

| Value | Behavior |
|-------|----------|
| `auto` (default) | Local CUDA if available; else Runpod when key set |
| `local` | Require CUDA + local VLM + Comfy (falls back to Runpod if no CUDA) |
| `runpod` | Always use Flash endpoint |

Generate logs show `backend=local|runpod`, endpoint id, and remote log lines. Cold start from scale-to-zero with large models can take **minutes**; keep `idle_timeout` / worker minutes in mind for cost.

### Network Volume model layout

Endpoint mounts volume `photoreal-models` at `/runpod-volume/` (datacenter `US-KS-2`, matching `runpod-flash` `DataCenter`). Workers need Comfy + weights on that volume — local `data/` on your PC is **not** used by Flash.

**Completeness check (automated):** before Generate submits a job, the portal ensures the volume passes a file/size layout check (Flux klein + LoRAs + VLM + `runtime/comfyui/main.py` + extra-paths yaml). If incomplete (or `FLASH_VOLUME_SYNCED` unset), it starts a short-lived Runpod pod attached to the volume that:

1. Re-runs the same completeness probe
2. Downloads only missing pieces via `scripts/download_models.py --all` (skips files already present)
3. Clones ComfyUI if needed, copies `scripts/flash_comfyui_extra_model_paths.yaml`
4. Sets `FLASH_VOLUME_SYNCED=1` in portal `.env` only after the check passes

```powershell
python scripts/flash_sync_volume.py          # fill if incomplete
python scripts/flash_sync_volume.py --check  # probe only
python scripts/flash_sync_volume.py --force  # ignore .env flag; still skip existing files
```

Expected layout:

```text
/runpod-volume/
  data/models/flux2/klein-base-9b/     # checkpoints + text_encoder
  data/models/loras/
  data/models/vlm/Qwen3-VL-8B-Instruct/
  runtime/comfyui/                     # Comfy checkout used by the worker
  comfyui_extra_model_paths.yaml       # from scripts/flash_comfyui_extra_model_paths.yaml
  .photoreal_volume_ready              # written after completeness passes
```

Local `scripts/download_models.py` remains the source of truth for *what* to download. First sync is billable (pod time + HF). Volume storage is ongoing.

## UI kit

Reusable white controls live in [`web/ui/`](../web/ui/). Portal page: [`web/portal/`](../web/portal/). Timeline studio: [`web/timeline/`](../web/timeline/) (opened after a successful Launch) — local NLE: import/drag media onto generic tracks, edit on a ruler/playhead timeline, preview at the playhead (in-memory only; no server persistence yet). **Create Character** opens a modal (also at `/character`) that runs auto-reprompt then `photoreal_gen` via `/api/character/*` (local CUDA + Comfy, or Runpod Flash when configured). Always use `PhotorealUI.createButton` / `createField`.

## Module map

| Piece | Path |
|-------|------|
| Entry | `python -m photoreal.portal` |
| App | `photoreal/portal/app.py` |
| Bootstrap | `photoreal/portal/bootstrap.py` |
| Supervisor | `photoreal/portal/supervisor.py` (+ `_linux` / `_windows`) |
