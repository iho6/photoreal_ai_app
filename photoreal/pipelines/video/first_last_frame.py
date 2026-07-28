"""First-last-frame video pipeline placeholder."""

from __future__ import annotations

from typing import Any

from photoreal.pipelines.base import Pipeline


class FirstLastFramePipeline(Pipeline):
    id = "first_last_frame"
    domain = "video"

    def run(self, **kwargs: Any) -> Any:
        raise NotImplementedError("FirstLastFramePipeline is a placeholder.")
