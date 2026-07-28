"""Image-to-video pipeline placeholder."""

from __future__ import annotations

from typing import Any

from photoreal.pipelines.base import Pipeline


class ImageToVideoPipeline(Pipeline):
    id = "image_to_video"
    domain = "video"

    def run(self, **kwargs: Any) -> Any:
        raise NotImplementedError("ImageToVideoPipeline is a placeholder.")
