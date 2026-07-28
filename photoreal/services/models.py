"""Model manager service interface stub."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class ModelService(ABC):
    """Resolve and load model assets. Implementations come later."""

    @abstractmethod
    def resolve(self, model_id: str) -> Path:
        raise NotImplementedError

    @abstractmethod
    def ensure_downloaded(self, model_id: str) -> Path:
        raise NotImplementedError
