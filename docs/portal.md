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

Opens `http://127.0.0.1:8010/` — enter HF + Git, **Save**, then **Launch**.

## Stages

1. **Stage 1 (script):** create `.venv`, `pip install -e ".[portal]"`, start API/portal on `:8010`, open browser.
2. **Stage 2 (Launch button):** write `.env`, install `.[photoreal-gen,vlm]` + curated Comfy deps (`requirements/comfyui-photoreal.txt`) **only if missing**, `download_models.py --all` (skips existing weights), then start **API + ComfyUI**.

Relaunch / click **Launch** again: cancels any in-flight Stage-2 (kills the download subprocess) and starts fresh. Civitai `.partial` files resume via HTTP Range; Hugging Face resumes incomplete cache shards. Stale Comfy on `:8188` is stopped before restart; a healthy API on `:8010` is left running. Stage-1 skips `.[portal]` when already importable.


| Service | Port |
|---------|------|
| API + portal | `127.0.0.1:8010` |
| ComfyUI | `127.0.0.1:8188` |

**Linux:** tmux session `photoreal` (windows `api`, `comfy`).  
**Windows:** detached processes; logs under `data/logs/api.log` and `data/logs/comfy.log`.

## Credentials

Saved to `.env` (gitignored). Git `user.name` / `user.email` use `git config --local` only.

## UI kit

Reusable white controls live in [`web/ui/`](../web/ui/). Portal page: [`web/portal/`](../web/portal/). Always use `PhotorealUI.createButton` / `createField`.

## Module map

| Piece | Path |
|-------|------|
| Entry | `python -m photoreal.portal` |
| App | `photoreal/portal/app.py` |
| Bootstrap | `photoreal/portal/bootstrap.py` |
| Supervisor | `photoreal/portal/supervisor.py` (+ `_linux` / `_windows`) |
