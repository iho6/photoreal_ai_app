"""Generation evaluation pipeline placeholder."""

from __future__ import annotations

from typing import Any

from photoreal.pipelines.base import Pipeline


class EvaluatePipeline(Pipeline):
    id = "evaluate"
    domain = "vision"

    def run(self, **kwargs: Any) -> Any:
        raise NotImplementedError("EvaluatePipeline is a placeholder.")
