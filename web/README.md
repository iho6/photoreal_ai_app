# Web

Portal UI (static) + shared design kit. Served by `python -m photoreal.portal`.

```text
web/
├── portal/          # launch credential portal
└── ui/              # shared Photoreal UI kit (Button, Field, tokens)
```

Always create controls via `PhotorealUI.createButton` / `PhotorealUI.createField` — do not invent one-off button markup.

Future Vite/Next studio should import or mirror `web/ui/` tokens and factories.
