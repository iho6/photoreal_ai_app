"""Health check route stub."""

from __future__ import annotations

from typing import Any


def health() -> dict[str, Any]:
    """Return a simple health payload (framework-agnostic stub)."""
    return {"status": "ok"}
