"""Unit tests for portal build fingerprint."""

from __future__ import annotations

from photoreal.portal.build_id import build_id
from photoreal.portal.app import create_app


def test_build_id_stable_and_hex():
    a = build_id()
    b = build_id()
    assert a == b
    assert len(a) == 16
    int(a, 16)  # raises if not hex


def test_health_includes_build():
    app = create_app()
    # FastAPI TestClient may not be installed; call the route endpoint directly.
    for route in app.routes:
        if getattr(route, "path", None) == "/api/health":
            out = route.endpoint()
            assert out["status"] == "ok"
            assert out["build"] == build_id()
            return
    raise AssertionError("/api/health route missing")
