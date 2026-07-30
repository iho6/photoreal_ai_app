# Requirements

Repo-owned install manifests. Prefer these over upstream trees under `runtime/`.

| File | Purpose |
|------|---------|
| `comfyui-photoreal.txt` | Lean ComfyUI deps for `photoreal_gen` (no workflow templates / embedded docs) |

Upstream ComfyUI’s full list remains at `runtime/comfyui/requirements.txt` for reference only — Launch and docs install the curated file.

```bash
pip install -r requirements/comfyui-photoreal.txt
```
