"""Base pipeline stub — subclass for each generation ability."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Pipeline(ABC):
    """One user-facing generation or analysis task."""

    id: str = "base"
    domain: str = "base"

    def validate(self, **kwargs: Any) -> None:
        """Validate inputs before run. Override as needed."""
        return None

    @abstractmethod
    def run(self, **kwargs: Any) -> Any:
        """Execute the pipeline. Placeholder subclasses raise NotImplementedError."""
        raise NotImplementedError
