"""Sound generation pipeline placeholder."""

from __future__ import annotations

from typing import Any

from photoreal.pipelines.base import Pipeline


class SoundPipeline(Pipeline):
    id = "sound"
    domain = "audio"

    def run(self, **kwargs: Any) -> Any:
        raise NotImplementedError("SoundPipeline is a placeholder.")
