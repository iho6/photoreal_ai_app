"""Invoker stub — create and run sessions against pipelines."""

from __future__ import annotations

from typing import Any

from photoreal.app.sessions import Session


class Invoker:
    """Primary app entry for surfaces (API / CLI). Placeholder only."""

    def create_session(self) -> Session:
        return Session()

    def invoke(self, session: Session, pipeline_id: str, **kwargs: Any) -> Any:
        raise NotImplementedError(
            f"Invoker.invoke({pipeline_id!r}) is a placeholder; wire pipelines later."
        )
