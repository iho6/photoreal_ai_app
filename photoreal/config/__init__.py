"""Application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    """Runtime configuration from env / defaults."""

    data_root: Path = field(default_factory=lambda: Path("data"))
    comfy_url: str = "http://127.0.0.1:8188"
    api_host: str = "127.0.0.1"
    api_port: int = 8010


def get_settings() -> Settings:
    """Return settings; honors PHOTOREAL_DATA_ROOT / COMFY_URL when set."""
    data = os.environ.get("PHOTOREAL_DATA_ROOT") or "data"
    comfy = os.environ.get("COMFY_URL") or "http://127.0.0.1:8188"
    host = os.environ.get("API_HOST") or "127.0.0.1"
    port_s = os.environ.get("API_PORT") or "8010"
    try:
        port = int(port_s)
    except ValueError:
        port = 8010
    return Settings(
        data_root=Path(data),
        comfy_url=comfy,
        api_host=host,
        api_port=port,
    )
