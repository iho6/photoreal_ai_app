"""Session stub for grouping related pipeline runs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class Session:
    """In-memory session placeholder."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: dict = field(default_factory=dict)
