"""Artifact / workspace storage service interface stub."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO


class StorageService(ABC):
    """Read/write workspace artifacts. Implementations come later."""

    @abstractmethod
    def put(self, key: str, data: bytes | BinaryIO) -> Path:
        raise NotImplementedError

    @abstractmethod
    def get(self, key: str) -> Path:
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError
