"""Multi-angle pipeline placeholder."""

from __future__ import annotations

from typing import Any

from photoreal.pipelines.base import Pipeline


class MultiAnglePipeline(Pipeline):
    id = "multi_angle"
    domain = "image"

    def run(self, **kwargs: Any) -> Any:
        raise NotImplementedError("MultiAnglePipeline is a placeholder.")
