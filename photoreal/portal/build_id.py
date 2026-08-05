"""Short fingerprint of portal + web source so Stage-1 can detect a stale API."""

from __future__ import annotations

import hashlib
from pathlib import Path

from photoreal.portal.paths import REPO_ROOT, WEB_ROOT

_SKIP_DIR_NAMES = {"__pycache__", ".git", "node_modules"}


def build_id() -> str:
    """Hash relative paths + mtimes + sizes under photoreal/ and web/."""
    roots = (REPO_ROOT / "photoreal", WEB_ROOT)
    h = hashlib.sha256()
    entries: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in _SKIP_DIR_NAMES for part in path.parts):
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            entries.append(f"{rel}:{st.st_mtime_ns}:{st.st_size}")
    for line in entries:
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()[:16]
