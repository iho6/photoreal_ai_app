"""Portal credentials, status schema, supervisor dry-run (no network/GPU)."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_portal_extra_in_pyproject() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "portal = [" in text
    assert "fastapi" in text


def test_launch_scripts_exist() -> None:
    assert Path("launch.sh").is_file()
    assert Path("launch.bat").is_file()
    assert Path("scripts/launch.sh").is_file()
    assert Path("scripts/launch.ps1").is_file()
    assert Path(".env.example").is_file()
    assert Path("web/portal/index.html").is_file()
    assert Path("web/ui/photoreal-ui.js").is_file()
    assert Path("web/ui/components/button.js").is_file()
    assert Path("web/ui/components/field.js").is_file()


def test_curated_comfy_requirements() -> None:
    from photoreal.portal.paths import COMFY_REQUIREMENTS

    assert COMFY_REQUIREMENTS.is_file()
    assert COMFY_REQUIREMENTS.name == "comfyui-photoreal.txt"
    assert COMFY_REQUIREMENTS.parent.name == "requirements"
    text = COMFY_REQUIREMENTS.read_text(encoding="utf-8")
    pkgs = "\n".join(
        ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")
    )
    assert "comfyui-frontend-package" in pkgs
    assert "comfyui-workflow-templates" not in pkgs
    assert "comfyui-embedded-docs" not in pkgs
    assert "kornia" not in pkgs
    assert "spandrel" not in pkgs
    assert "PyOpenGL" not in pkgs
    assert "comfy-angle" not in pkgs

    # Bootstrap Stage-2 must install the curated file
    import photoreal.portal.bootstrap as boot

    src = Path(boot.__file__).read_text(encoding="utf-8")
    assert "COMFY_REQUIREMENTS" in src
    assert "runtime/comfyui/requirements.txt" not in src


def test_credentials_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import photoreal.portal.credentials as creds
    import photoreal.portal.paths as paths

    env_path = tmp_path / ".env"
    monkeypatch.setattr(creds, "ENV_PATH", env_path)
    monkeypatch.setattr(paths, "ENV_PATH", env_path)
    monkeypatch.setattr(creds, "_git_config_get", lambda key: None)
    monkeypatch.setattr(creds, "_git_config_set", lambda key, value: None)

    with pytest.raises(ValueError):
        creds.save_credentials(hf_token="")

    out = creds.save_credentials(
        hf_token="hf_test_token",
        civitai_api_token="civ_test",
        git_user_name="Test User",
        git_user_email="test@example.com",
    )
    assert out["hf_token_set"] is True
    assert env_path.is_file()
    assert "hf_test_token" in env_path.read_text(encoding="utf-8")

    # Masked reload should not echo raw token to API consumers
    loaded = creds.load_credentials()
    assert loaded["hf_token_set"] is True
    assert loaded["hf_token"] == "••••••••"

    # Bullet placeholder must not wipe existing token
    creds.save_credentials(hf_token="••••••••")
    assert "hf_test_token" in env_path.read_text(encoding="utf-8")


def test_supervisor_dry_run_commands() -> None:
    from photoreal.portal.supervisor import dry_run_commands

    cmds = dry_run_commands()
    assert "photoreal.portal" in " ".join(cmds["api"])
    assert "main.py" in " ".join(cmds["comfy"])
    assert "8188" in " ".join(cmds["comfy"])
    assert cmds["session"] == "photoreal"


def test_portal_app_status_and_health() -> None:
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from photoreal.portal.app import create_app

    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    s = client.get("/api/status")
    assert s.status_code == 200
    body = s.json()
    assert "health" in body
    assert "credentials" in body
    assert "launch" in body
    assert "commands_dry_run" in body

    home = client.get("/")
    assert home.status_code == 200
    assert b"Photoreal" in home.content
