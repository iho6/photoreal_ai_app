# Web

Portal UI (static) + shared design kit. Served by `python -m photoreal.portal`.

```text
web/
├── portal/          # launch credential portal
├── timeline/        # post-launch local NLE (preview + timeline)
├── character/       # create-character studio (modal + /character)
└── ui/              # shared Photoreal UI kit (Button, Field, tokens)
```

Timeline (`/timeline`): client-only editor — generic tracks, local file import / drag-drop, move/trim/split, transport + playhead preview. No server persistence yet.

Character (`/character` or Create Character modal): prompt → auto-reprompt → photoreal_gen (local CUDA or Runpod Flash when configured); zoomable preview + draggable gallery/groups. Outputs under `data/outputs/characters/`.

Always create controls via `PhotorealUI.createButton` / `PhotorealUI.createField` — do not invent one-off button markup.

Future Vite/Next studio should import or mirror `web/ui/` tokens and factories.
