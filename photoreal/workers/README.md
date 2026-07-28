# Workers

Fal-style deploy entrypoints. Each worker should:

1. Load config / models in a `setup`-like path.
2. Call the matching `photoreal.pipelines.*` implementation.
3. Stay free of UI / session orchestration (that stays in `photoreal.app`).

Add modules here when a pipeline needs a remote or packaged GPU process, e.g. `image_edit.py` → `ImageEditWorker`.
