# Scripts

Ops and bootstrap only (not generation abilities — those live under `photoreal/pipelines/`).

| Script | Purpose |
|--------|---------|
| `launch.sh` / `launch.ps1` | Stage-1: venv + portal (prefer repo-root `./launch.sh` or `launch.bat`) |
| `download_models.py` | Single downloader; `--<ability>` flags and `--all` |

```bash
# Portal (Linux primary)
./launch.sh

# Weights only
pip install -e ".[photoreal-gen]"
pip install -r requirements/comfyui-photoreal.txt
python scripts/download_models.py --photoreal-gen
python scripts/download_models.py --photoreal-gen --with-snofs
pip install -e ".[vlm]"
python scripts/download_models.py --vlm
python scripts/download_models.py --all
python scripts/download_models.py --all --loras-only
```

See [docs/portal.md](../docs/portal.md), [docs/photoreal_gen.md](../docs/photoreal_gen.md), [docs/vlm.md](../docs/vlm.md).
