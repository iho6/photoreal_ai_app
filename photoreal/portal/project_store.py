"""Default project document + user media under data/workspace/projects/default/."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from photoreal.portal.paths import REPO_ROOT

PROJECT_ID = "default"
PROJECTS_ROOT = REPO_ROOT / "data" / "workspace" / "projects"
PROJECT_DIR = PROJECTS_ROOT / PROJECT_ID
MEDIA_DIR = PROJECT_DIR / "media"
PROJECT_JSON = PROJECT_DIR / "project.json"
MEDIA_URL_PREFIX = "/project-media"
SCHEMA_VERSION = 1

_SAFE_EXT = re.compile(r"^[a-zA-Z0-9]{1,12}$")


def empty_project() -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "updatedAt": None,
        "timeline": {
            "fps": 30,
            "pxPerSec": 80,
            "playhead": 0,
            "snap": True,
            "tracks": [],
            "clips": [],
            "selection": None,
        },
        "characters": {"usedUrls": []},
    }


def ensure_project_dirs() -> Path:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return PROJECT_DIR


def load_project() -> dict[str, Any]:
    ensure_project_dirs()
    if not PROJECT_JSON.is_file():
        return empty_project()
    try:
        data = json.loads(PROJECT_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_project()
    if not isinstance(data, dict):
        return empty_project()
    if "timeline" not in data or not isinstance(data.get("timeline"), dict):
        data["timeline"] = empty_project()["timeline"]
    if "characters" not in data or not isinstance(data.get("characters"), dict):
        data["characters"] = {"usedUrls": []}
    data.setdefault("version", SCHEMA_VERSION)
    return data


def save_project(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_project_dirs()
    if not isinstance(payload, dict):
        raise ValueError("project payload must be an object")
    doc = {
        "version": int(payload.get("version") or SCHEMA_VERSION),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "timeline": payload.get("timeline")
        if isinstance(payload.get("timeline"), dict)
        else empty_project()["timeline"],
        "characters": payload.get("characters")
        if isinstance(payload.get("characters"), dict)
        else {"usedUrls": []},
    }
    tmp = PROJECT_JSON.with_suffix(".json.tmp")
    text = json.dumps(doc, indent=2, ensure_ascii=False)
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(PROJECT_JSON)
    return doc


def _extension_for(filename: str | None, content_type: str | None) -> str:
    name = (filename or "").strip()
    if "." in name:
        ext = name.rsplit(".", 1)[-1].lower()
        if _SAFE_EXT.match(ext):
            return ext
    ct = (content_type or "").lower()
    if "webm" in ct:
        return "webm"
    if "mp4" in ct:
        return "mp4"
    if "png" in ct:
        return "png"
    if "jpeg" in ct or "jpg" in ct:
        return "jpg"
    if "webp" in ct:
        return "webp"
    if "gif" in ct:
        return "gif"
    if "wav" in ct:
        return "wav"
    if "mpeg" in ct or "mp3" in ct:
        return "mp3"
    return "bin"


def save_media(
    data: bytes | BinaryIO,
    *,
    filename: str | None = None,
    content_type: str | None = None,
) -> dict[str, str]:
    ensure_project_dirs()
    if hasattr(data, "read"):
        raw = data.read()
    else:
        raw = data
    if not isinstance(raw, (bytes, bytearray)):
        raise TypeError("media data must be bytes")
    ext = _extension_for(filename, content_type)
    asset_id = uuid.uuid4().hex
    out_name = f"{asset_id}.{ext}"
    out_path = MEDIA_DIR / out_name
    out_path.write_bytes(bytes(raw))
    url = f"{MEDIA_URL_PREFIX}/{out_name}"
    return {"id": asset_id, "url": url, "filename": out_name}
