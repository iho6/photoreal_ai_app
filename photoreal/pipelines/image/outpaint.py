"""Outpaint pipeline placeholder."""

from __future__ import annotations

from typing import Any

from photoreal.pipelines.base import Pipeline


class OutpaintPipeline(Pipeline):
    id = "outpaint"
    domain = "image"

    def run(self, **kwargs: Any) -> Any:
        raise NotImplementedError("OutpaintPipeline is a placeholder.")
