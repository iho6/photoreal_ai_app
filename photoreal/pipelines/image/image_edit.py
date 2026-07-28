"""Image edit pipeline placeholder."""

from __future__ import annotations

from typing import Any

from photoreal.pipelines.base import Pipeline


class ImageEditPipeline(Pipeline):
    id = "image_edit"
    domain = "image"

    def run(self, **kwargs: Any) -> Any:
        raise NotImplementedError("ImageEditPipeline is a placeholder.")
