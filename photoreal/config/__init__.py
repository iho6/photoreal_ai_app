"""Application settings placeholders."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    """Runtime configuration stub. Load from env / files later."""

    data_root: Path = field(default_factory=lambda: Path("data"))
    comfy_url: str = "http://127.0.0.1:8188"
    api_host: str = "127.0.0.1"
    api_port: int = 8010


def get_settings() -> Settings:
    """Return default settings (placeholder)."""
    return Settings()
