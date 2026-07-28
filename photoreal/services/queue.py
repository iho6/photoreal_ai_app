"""Job queue service interface stub."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable


class QueueService(ABC):
    """Enqueue and run generation jobs. Implementations come later."""

    @abstractmethod
    def enqueue(self, job_id: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError

    @abstractmethod
    def status(self, job_id: str) -> str:
        raise NotImplementedError
