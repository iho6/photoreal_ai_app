# Photoreal AI App

Hybrid generative AI studio skeleton: local orchestration with pluggable pipelines (and later workers), plus API / CLI / web surfaces.

**This repo currently has placeholders only** — no models, Comfy workflows, or generation logic yet.

## Layout

| Path | Role |
|------|------|
| `photoreal/` | Installable Python package |
| `photoreal/pipelines/` | Generation abilities (catalog) |
| `photoreal/services/` | Shared infra interfaces (storage, models, queue) |
| `photoreal/app/` | Session / job orchestration |
| `photoreal/workers/` | Deployable worker entrypoints (fal-style) |
| `photoreal/api/` | HTTP API |
| `photoreal/cli/` | Thin CLI |
| `web/` | Frontend studio (scaffold later) |
| `runtime/` | Engine hosts (e.g. ComfyUI) |
| `data/` | Models, inputs, outputs, workspace |
| `docs/architecture.md` | Layer rules and naming |

## Growing abilities

1. Add a module under `photoreal/pipelines/<domain>/` (e.g. `image/relight.py`).
2. Subclass `photoreal.pipelines.base.Pipeline`.
3. Optionally add a matching worker under `photoreal/workers/`.
4. Wire a route or CLI command that calls the invoker — not the engine directly.

Name pipelines by **task** (`image_edit`), not by model (`qwen_edit_service`).

## Quickstart (skeleton)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

See [docs/architecture.md](docs/architecture.md) for the layer diagram.
