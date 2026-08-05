"""Workspace artifact storage: thin facade over project media + keys."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

from photoreal.portal import project_store


class StorageService(ABC):
    """Read/write workspace artifacts."""

    @abstractmethod
    def put(self, key: str, data: bytes | BinaryIO) -> Path:
        raise NotImplementedError

    @abstractmethod
    def get(self, key: str) -> Path:
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError


class ProjectMediaStorage(StorageService):
    """Store blobs under data/workspace/projects/default/media/."""

    def put(self, key: str, data: bytes | BinaryIO) -> Path:
        project_store.ensure_project_dirs()
        name = Path(key).name
        if not name or name in (".", ".."):
            raise ValueError("invalid storage key")
        path = project_store.MEDIA_DIR / name
        if hasattr(data, "read"):
            raw = data.read()
        else:
            raw = data
        path.write_bytes(bytes(raw))
        return path

    def get(self, key: str) -> Path:
        name = Path(key).name
        path = project_store.MEDIA_DIR / name
        if not path.is_file():
            raise FileNotFoundError(key)
        return path

    def delete(self, key: str) -> None:
        name = Path(key).name
        path = project_store.MEDIA_DIR / name
        if path.is_file():
            path.unlink()
