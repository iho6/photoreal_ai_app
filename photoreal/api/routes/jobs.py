"""Jobs route stub — submit / poll generation jobs later."""

from __future__ import annotations

from typing import Any


def create_job(pipeline_id: str, **kwargs: Any) -> dict[str, Any]:
    raise NotImplementedError(
        f"create_job({pipeline_id!r}) is a placeholder; wire invoker later."
    )


def get_job(job_id: str) -> dict[str, Any]:
    raise NotImplementedError(
        f"get_job({job_id!r}) is a placeholder; wire queue/status later."
    )
