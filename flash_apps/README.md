# Flash apps

Each subdirectory is a **standalone Flash project root** (`flash deploy` runs inside it).
One app = one serverless endpoint = one ≤1.5 GB artifact. Do **not** put multiple
`@Endpoint` definitions in the same folder (that merges deps into one fat image).

| App id | Endpoint name | GPU | Volume | Status | Deploy |
|--------|---------------|-----|--------|--------|--------|
| `character` | `photoreal-character-4090` | RTX 4090 | `photoreal-models` @ US-CA-2 | active | `bash scripts/flash_deploy_app.sh character` |
| `wan_animate` | TBD | TBD | TBD | planned | — |

Per-app details live in `<app>/META.md`. Shared CUDA excludes: `_shared/excludes.txt`.

Models and ComfyUI live on the Network Volume — not in the Flash artifact.
See [docs/portal.md](../docs/portal.md).
