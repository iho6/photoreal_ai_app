"""Text-to-image pipeline placeholder."""

from __future__ import annotations

from typing import Any

from photoreal.pipelines.base import Pipeline


class TextToImagePipeline(Pipeline):
    id = "text_to_image"
    domain = "image"

    def run(self, **kwargs: Any) -> Any:
        raise NotImplementedError("TextToImagePipeline is a placeholder.")
