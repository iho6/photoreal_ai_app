# Scripts

Ops and bootstrap only (not generation abilities — those live under `photoreal/pipelines/`).

| Script | Purpose |
|--------|---------|
| `download_models.py` | Single downloader; `--<ability>` flags and `--all` |

```bash
pip install -e ".[photoreal-gen]"
python scripts/download_models.py --photoreal-gen
python scripts/download_models.py --photoreal-gen --with-snofs
pip install -e ".[vlm]"
python scripts/download_models.py --vlm
python scripts/download_models.py --all
python scripts/download_models.py --all --loras-only
```

See [docs/photoreal_gen.md](../docs/photoreal_gen.md) and [docs/vlm.md](../docs/vlm.md).
