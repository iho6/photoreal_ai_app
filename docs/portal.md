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

1. **Stage 1 (script):** prefer drive-local `runtime/python` → heal/create `.venv` bound to it → `pip install -e ".[portal]"` if needed → start API/portal on `:8010` → open browser **only after** `/api/health` succeeds.
2. **Stage 2 (Launch button):** write `.env`, install `.[photoreal-gen,vlm]` + curated Comfy deps (`requirements/comfyui-photoreal.txt`) **only if missing**, `download_models.py --photoreal-gen --vlm` when local character weights are missing, then start **API + ComfyUI**. On success the browser opens the **timeline** studio at `/timeline`. Wan/SAM/depth stacks are **not** pulled by Launch — use `scripts/download_models.py --wan-animate` (etc.) when needed.

### Multi-app Comfy on the same PC

Generate/Launch **detect** whether `:8188` is this repo’s Comfy (`runtime/comfyui` / `comfy.pid`):

- **Ours + healthy + photoreal models listed** → reuse (no restart).
- **Ours but stale** (wrong/empty model lists) → restart only our process.
- **Another app owns `:8188`** → leave it alone; start this repo’s Comfy on the next free port (`8189`…) and set `COMFY_URL` for the portal session. Job logs show the chosen URL.

Force restart via the portal API still claims the preferred port when you explicitly ask for a hard reset.

Before any pip work, the Windows launch script:

1. Ensures a **drive-local CPython ≥ 3.11** under [`runtime/python/`](../runtime/python/) (downloaded once onto the repo volume via NuGet; gitignored). Prefer this over each PC’s `C:\Users\...\Python` so moving the volume does not orphan `.venv`.
2. Falls back to system `py` / PATH / install roots (or `winget`) only if portable bootstrap fails — that path **ties `.venv` to the machine**.
3. Validates `.venv`: interpreter runs; `pyvenv.cfg` `home=` / `executable=` exist; when `runtime/python` is present, home must sit **under** it (forces one-time migrate off system Python); create-path **drive letter** must match the repo drive (e.g. keep the volume as **`H:`** on every PC).
4. Installs portal deps only when missing, starts the API, then opens the browser. If health never succeeds, it prints log tails and exits non-zero (no dead browser tab).
5. **Build fingerprint:** `/api/health` returns a short hash of `photoreal/` + `web/`. If a healthy API is already on `:8010` but its `build` does not match the repo, Stage-1 **restarts** it so new routes (e.g. `/api/project`) are live. Unchanged code keeps the fast “already healthy” path.
6. **Cache-bust open:** Stage-1 opens the portal as `http://127.0.0.1:8010/?b=<build>` so a previously cached HTML shell is re-fetched once after a code change.

**HTML shells and assets:** `/`, `/timeline`, and `/character` are served with `Cache-Control: no-store` (plus `no-cache` / `Pragma` / `Expires`). Every `<script>` / `<link>` URL and a `<meta name="portal-build">` tag carry the same build id from `/api/health`. You never need to bump `?v=` by hand — editing anything under `photoreal/` or `web/` changes the fingerprint and therefore every asset URL. Open tabs also poll `/api/health` every ~15s via `/ui/build_guard.js`; if the server build differs from the page meta, a fixed red banner offers **Reload**.

**Stale portal symptom:** timeline save status or Record Reference errors saying **“Portal API is out of date (no /api/project)”** mean the browser is talking to an old API process. Re-run `launch.bat` / `launch.sh` (it will restart). If a red “Portal code updated” banner appears, click **Reload**. Clips recorded against a stale API or a stale cached frontend were never saved and cannot be recovered.

**Portable volume checklist:** assign the same drive letter on every host (plan assumes **`H:`**); install a compatible **NVIDIA driver** on each host (CUDA cannot live only on the disk). Do not commit `runtime/python/` or `.venv/`. Fresh clones elsewhere bootstrap their own `runtime/python` + download weights via Launch — they do not need your `H:` tree.

**RTX 50 / Blackwell:** local Generate needs a PyTorch **CUDA 12.8** (`cu128`) wheel. Stage-2 Launch and Generate env-check call `nvidia-smi`; when a GPU is present but `.venv` still has a CPU/old torch, they auto-install from `https://download.pytorch.org/whl/cu128`. Plain `pip install torch` from PyPI is not enough. If `nvidia-smi` is missing on the host, Generate correctly falls back to Runpod Flash.

**Linux:** Stage-1 still uses system Python + repo `.venv` (no portable Windows runtime). GPU hosts remain the primary Linux path.

Relaunch / click **Launch** again: cancels any in-flight Stage-2 (kills the download subprocess) and starts fresh. Civitai `.partial` files resume via HTTP Range; Hugging Face resumes incomplete cache shards. Stale Comfy on `:8188` is stopped before restart; a healthy API on `:8010` is left running **only if** its build fingerprint still matches the repo. Stage-1 skips `.[portal]` when already importable.


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

Flash apps live under [`flash_apps/`](../flash_apps/README.md) — **one folder per endpoint** (own GPU, deps, ≤1.5 GB artifact). Character Generate uses `flash_apps/character/` (`photoreal-character-4090` on RTX 4090). Future features (e.g. WAN animate) get their own folder; see the index table in that README and each app’s `META.md`.

Flash setup is **required** for Launch (portal Runpod API key). Flash CLI is **macOS/Linux only**. On Windows:

- **No WSL distro (recommended here):** Generate dispatches GitHub Actions (`.github/workflows/flash-deploy-app.yml`, `app=character`) when the endpoint is missing.
- **WSL2 + Ubuntu:** `.\scripts\flash_deploy_app.ps1 character` (or `.\scripts\flash_deploy_character.ps1`).

The portal calls Runpod Serverless HTTP with the saved key after deploy.

Docs: [Flash overview](https://docs.runpod.io/flash/overview), [Windows WSL2](https://docs.runpod.io/flash/windows-wsl2).

### Windows: Flash deploy via GitHub Actions (no local Ubuntu)

One-time setup:

1. Push this repo to GitHub (workflow file must be on the branch you dispatch).
2. On the portal, save **Runpod API key**, **HF token**, and a **GitHub token** with classic `repo` scope (or fine-grained: **Actions** + **Secrets** + **Contents**).

Save or Launch **auto-pushes** Actions secrets `RUNPOD_API_KEY` and `HF_TOKEN` to the GitHub repo via API — you do not need to enter them under Settings → Secrets on the website (unless the token lacks Secrets permission).

Then **Generate** auto-deploys when `photoreal-character-4090` is missing. Manual: **Actions → Flash deploy app → Run workflow** (app=`character`).

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
   - Manually: Actions → Flash deploy app / `.\scripts\flash_deploy_app.ps1 character` / `bash scripts/flash_deploy_app.sh character`.
3. Network Volume models are **auto-synced on first Generate** when incomplete (see below); or run `python scripts/flash_sync_volume.py`.

Deploy stages an allowlisted `photoreal/` subset into `flash_apps/character/` and excludes torch/nvidia CUDA wheels (`flash_apps/_shared/excludes.txt`) so the artifact stays under RunPod’s 1.5 GB limit. Comfy/weights stay on the Network Volume.

### Smoke (RTX 4090)

```bash
# in WSL, from repo root
pip install runpod-flash
# or rely on portal .env RUNPOD_API_KEY
bash scripts/flash_deploy_app.sh character
python scripts/flash_smoke_4090.py
```

Success log must show a real `NVIDIA GeForce RTX 4090` string.

### Character endpoint (manual)

```powershell
# Windows (WSL)
.\scripts\flash_deploy_app.ps1 character
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

Endpoint mounts volume `photoreal-models` at `/runpod-volume/` (datacenter `US-CA-2`, matching `runpod-flash` `DataCenter` + live volume API). Workers need Comfy + weights on that volume — local `data/` on your PC is **not** used by Flash.

**Restart the portal** after Flash datacenter / volume code changes so it reloads `VOLUME_DATACENTER`. Sync pods are always scheduled in the volume’s own datacenter; a stale portal process can otherwise attach the wrong way and fail in seconds.

**Completeness check (automated):** before Generate submits a job, the portal ensures the volume passes a file/size layout check (Flux klein + LoRAs + VLM + `runtime/comfyui/main.py` + extra-paths yaml). If incomplete (or `FLASH_VOLUME_SYNCED` unset), it starts a short-lived Runpod pod attached to the volume that:

1. Re-runs the same completeness probe
2. Downloads only missing pieces via `scripts/download_models.py --photoreal-gen --vlm` (skips files already present). Other abilities stay CLI (`--sam3`, `--depth`, `--wan-animate`, `--all`, …).
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

Reusable white controls live in [`web/ui/`](../web/ui/). Portal page: [`web/portal/`](../web/portal/). Timeline studio: [`web/timeline/`](../web/timeline/) (opened after a successful Launch) — local NLE: import/drag media onto generic tracks, edit on a ruler/playhead timeline, preview at the playhead. **Autosaves** the default project to `data/workspace/projects/default/project.json` (user media under `media/`, served at `/project-media/`). Stage outputs stay under `data/outputs/*`; clip fields bind them so Segment → Depth → Inpaint → Pose Lock → Wan lineage survives refresh. **Create Character** opens a modal (also at `/character`) that runs auto-reprompt then `photoreal_gen` via `/api/character/*` (local CUDA + Comfy, or Runpod Flash when configured). **Record Reference** opens a camera modal: local **Vosk** listens for spoken “start” / “stop” (on-screen buttons always work; no cloud ASR), then review → **Save** uploads WebM to project media and places a `role=reference` clip on a **References** track. Right-click a clip or the preview → **Replace Character** stages: Segment → Depth → Character Reference → Pose Lock (see [replace_character.md](replace_character.md)). Always use `PhotorealUI.createButton` / `createField`.

### Local voice (Vosk)

Fully offline keyword spotting for Record Reference:

```bash
pip install -e ".[portal]"   # includes vosk
python scripts/download_models.py --vosk
```

Model path: `data/models/vosk/vosk-model-small-en-us-0.15/`. APIs: `GET /api/voice/status`, `POST /api/voice/command` (raw s16le mono PCM @ 16 kHz → `{command: start|stop|none}`).

## Module map

| Piece | Path |
|-------|------|
| Entry | `python -m photoreal.portal` |
| App | `photoreal/portal/app.py` |
| Voice (Vosk) | `photoreal/portal/voice_vosk.py` |
| Record Reference UI | `web/reference/` |
| Bootstrap | `photoreal/portal/bootstrap.py` |
| Supervisor | `photoreal/portal/supervisor.py` (+ `_linux` / `_windows`) |
