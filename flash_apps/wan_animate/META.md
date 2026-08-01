# Flash app: `wan_animate`

| Field | Value |
|-------|--------|
| **App id** | `wan_animate` |
| **Endpoint name** | TBD |
| **GPU** | TBD |
| **Datacenter** | TBD |
| **Network volume** | TBD |
| **Worker** | TBD |
| **Portal cache** | TBD |
| **Status** | planned |

## What it will do

WAN animate (and related video) Flash worker — separate artifact from `character`
so GPU/deps stay isolated under the 1.5 GB limit.

## Next steps

1. Add `endpoint.py` + `MANIFEST.txt` + `.gitignore` (mirror `flash_apps/character/`).
2. Implement worker under `photoreal/flash/` (or a dedicated module).
3. `bash scripts/flash_deploy_app.sh wan_animate`
4. Add a row to [flash_apps/README.md](../README.md) and wire portal resolve-by-name.
