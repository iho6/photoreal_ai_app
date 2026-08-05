"""Unit tests for default project store."""

from __future__ import annotations

import json

from photoreal.portal import project_store


def test_empty_and_roundtrip(tmp_path, monkeypatch):
    root = tmp_path / "projects" / "default"
    monkeypatch.setattr(project_store, "PROJECT_DIR", root)
    monkeypatch.setattr(project_store, "MEDIA_DIR", root / "media")
    monkeypatch.setattr(project_store, "PROJECT_JSON", root / "project.json")

    empty = project_store.load_project()
    assert empty["version"] == 1
    assert empty["timeline"]["tracks"] == []
    assert empty["characters"]["usedUrls"] == []

    payload = {
        "version": 1,
        "timeline": {
            "fps": 24,
            "pxPerSec": 80,
            "playhead": 1.5,
            "snap": True,
            "tracks": [{"id": "trk_1", "name": "References", "locked": False, "hidden": False, "height": 64}],
            "clips": [
                {
                    "id": "clip_1",
                    "trackId": "trk_1",
                    "name": "Reference 1",
                    "mediaType": "video",
                    "src": "/project-media/abc.webm",
                    "start": 0,
                    "duration": 2,
                    "inPoint": 0,
                    "sourceDuration": 2,
                    "role": "reference",
                    "refSlot": 1,
                    "segmentMaskUrl": "/sam3-outputs/mask.png",
                    "depthUrl": "/depth-outputs/d.png",
                }
            ],
            "selection": None,
        },
        "characters": {"usedUrls": ["/character-outputs/c.png"]},
    }
    saved = project_store.save_project(payload)
    assert saved["updatedAt"]
    assert project_store.PROJECT_JSON.is_file()

    loaded = project_store.load_project()
    assert loaded["timeline"]["fps"] == 24
    assert loaded["timeline"]["clips"][0]["segmentMaskUrl"] == "/sam3-outputs/mask.png"
    assert loaded["timeline"]["clips"][0]["depthUrl"] == "/depth-outputs/d.png"
    assert loaded["characters"]["usedUrls"] == ["/character-outputs/c.png"]


def test_save_media(tmp_path, monkeypatch):
    root = tmp_path / "projects" / "default"
    monkeypatch.setattr(project_store, "PROJECT_DIR", root)
    monkeypatch.setattr(project_store, "MEDIA_DIR", root / "media")
    monkeypatch.setattr(project_store, "PROJECT_JSON", root / "project.json")

    info = project_store.save_media(
        b"hello",
        filename="ref.webm",
        content_type="video/webm",
    )
    assert info["url"].startswith("/project-media/")
    assert info["url"].endswith(".webm")
    path = root / "media" / info["filename"]
    assert path.read_bytes() == b"hello"
