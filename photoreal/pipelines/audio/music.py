"""Music generation pipeline placeholder."""

from __future__ import annotations

from typing import Any

from photoreal.pipelines.base import Pipeline


class MusicPipeline(Pipeline):
    id = "music"
    domain = "audio"

    def run(self, **kwargs: Any) -> Any:
        raise NotImplementedError("MusicPipeline is a placeholder.")
