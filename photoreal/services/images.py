"""Image I/O service interface stub."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class ImageService(ABC):
    """Load / save / normalize images. Implementations come later."""

    @abstractmethod
    def load(self, path: Path | str) -> Any:
        raise NotImplementedError

    @abstractmethod
    def save(self, image: Any, path: Path | str) -> Path:
        raise NotImplementedError
