# Web

Portal UI (static) + shared design kit. Served by `python -m photoreal.portal`.

```text
web/
├── portal/          # launch credential portal
├── timeline/        # post-launch local NLE (preview + timeline)
├── character/       # create-character studio (modal + /character)
├── reference/       # Record Reference modal (camera + local Vosk)
└── ui/              # shared Photoreal UI kit (Button, Field, tokens)
```

Timeline (`/timeline`): local NLE — generic tracks, file import / drag-drop, move/trim/split, transport + playhead preview. **Persists** the default project via `GET/PUT /api/project` and `POST /api/project/media` (`data/workspace/projects/default/`). User media is uploaded to `/project-media/`; Replace Character / Wan stage URLs under `/…-outputs/` round-trip in `project.json`. **Create Location** imports images as `role=location` on a Locations track (backdrop for Replace Character). **Record Reference** (lazy-loaded from `/reference-assets/`) captures webcam WebM, optional local Vosk Start/Stop via `/api/voice/*`, and saves `role=reference` clips with auto `refSlot` (Ref 1, Ref 2, …) onto a **References** track. Clip/preview context menu **Replace Character** stages: Segment (cutout) → Depth → Character Reference (gallery → inpaint) → Pose Lock. See [docs/replace_character.md](../docs/replace_character.md).

Character (`/character` or Create Character modal): prompt → auto-reprompt → photoreal_gen (local CUDA or Runpod Flash when configured); zoomable preview + draggable gallery/groups. Outputs under `data/outputs/characters/`.

Always create controls via `PhotorealUI.createButton` / `PhotorealUI.createField` — do not invent one-off button markup.

Future Vite/Next studio should import or mirror `web/ui/` tokens and factories.
