"""Media describe (VLM) pipeline placeholder."""

from __future__ import annotations

from typing import Any

from photoreal.pipelines.base import Pipeline


class DescribePipeline(Pipeline):
    id = "describe"
    domain = "vision"

    def run(self, **kwargs: Any) -> Any:
        raise NotImplementedError("DescribePipeline is a placeholder.")
