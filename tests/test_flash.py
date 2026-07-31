"""Flash backend resolution, endpoint id resolve, and env check (no network)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_resolve_generate_backend_auto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import photoreal.portal.credentials as creds
    import photoreal.flash.backend as backend

    env_path = tmp_path / ".env"
    env_path.write_text(
        "HF_TOKEN=hf\nRUNPOD_API_KEY=rp\nFLASH_CHARACTER_ENDPOINT=ep1\n"
        "GENERATE_BACKEND=auto\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(creds, "ENV_PATH", env_path)
    monkeypatch.setattr(backend, "torch_cuda_available", lambda: False)
    choice = backend.resolve_generate_backend()
    assert choice["backend"] == "runpod"
    assert choice["endpoint_id"] == "ep1"
    assert choice["runpod_key"] is True

    monkeypatch.setattr(backend, "torch_cuda_available", lambda: True)
    choice2 = backend.resolve_generate_backend()
    assert choice2["backend"] == "local"


def test_resolve_forces_runpod_without_cuda_even_if_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import photoreal.portal.credentials as creds
    import photoreal.flash.backend as backend

    env_path = tmp_path / ".env"
    env_path.write_text(
        "HF_TOKEN=hf\nRUNPOD_API_KEY=rp\nFLASH_CHARACTER_ENDPOINT=ep1\n"
        "GENERATE_BACKEND=local\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(creds, "ENV_PATH", env_path)
    monkeypatch.setattr(backend, "torch_cuda_available", lambda: False)
    choice = backend.resolve_generate_backend()
    assert choice["backend"] == "runpod"


def test_assert_generate_env_runpod_ok_without_cached_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import photoreal.portal.credentials as creds
    import photoreal.portal.env_check as env_check
    import photoreal.flash.backend as backend

    env_path = tmp_path / ".env"
    env_path.write_text(
        "HF_TOKEN=hf\nRUNPOD_API_KEY=rp\nGENERATE_BACKEND=runpod\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(creds, "ENV_PATH", env_path)
    monkeypatch.setattr(backend, "torch_cuda_available", lambda: False)
    info = env_check.assert_generate_env()
    assert info["backend"] == "runpod"
    assert info.get("endpoint_id") in (None, "")


def test_assert_generate_env_fails_without_key_or_cuda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import photoreal.portal.credentials as creds
    import photoreal.portal.env_check as env_check
    import photoreal.flash.backend as backend

    env_path = tmp_path / ".env"
    env_path.write_text("HF_TOKEN=hf\nGENERATE_BACKEND=auto\n", encoding="utf-8")
    monkeypatch.setattr(creds, "ENV_PATH", env_path)
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    monkeypatch.delenv("FLASH_CHARACTER_ENDPOINT", raising=False)
    monkeypatch.setattr(backend, "torch_cuda_available", lambda: False)
    with pytest.raises(RuntimeError, match="Runpod Flash"):
        env_check.assert_generate_env()


def test_resolve_ignores_terminal_runpod_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Portal .env is sole source — terminal RUNPOD_API_KEY must not count."""
    import photoreal.portal.credentials as creds
    import photoreal.flash.backend as backend

    env_path = tmp_path / ".env"
    env_path.write_text(
        "HF_TOKEN=hf\nGENERATE_BACKEND=auto\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(creds, "ENV_PATH", env_path)
    monkeypatch.setenv("RUNPOD_API_KEY", "from_terminal")
    monkeypatch.setenv("FLASH_CHARACTER_ENDPOINT", "from_terminal")
    monkeypatch.setattr(backend, "torch_cuda_available", lambda: False)
    choice = backend.resolve_generate_backend()
    assert choice["runpod_key"] is False
    assert choice["endpoint_id"] == ""


def test_resolve_character_endpoint_preferred_id() -> None:
    from photoreal.flash.endpoints import resolve_character_endpoint_id

    assert (
        resolve_character_endpoint_id("key", preferred_id="ep_cached") == "ep_cached"
    )


def test_resolve_character_endpoint_one_match() -> None:
    from photoreal.flash.endpoints import (
        CHARACTER_ENDPOINT_NAME,
        resolve_character_endpoint_id,
    )

    mock = MagicMock()
    mock.get.return_value.status_code = 200
    mock.get.return_value.json.return_value = [
        {"id": "other", "name": "something-else"},
        {"id": "ep_match", "name": CHARACTER_ENDPOINT_NAME, "createdAt": "2026-01-01"},
    ]
    eid = resolve_character_endpoint_id("key", client=mock)
    assert eid == "ep_match"
    mock.get.assert_called_once()


def test_resolve_character_endpoint_picks_newest() -> None:
    from photoreal.flash.endpoints import (
        CHARACTER_ENDPOINT_NAME,
        resolve_character_endpoint_id,
    )

    mock = MagicMock()
    mock.get.return_value.status_code = 200
    mock.get.return_value.json.return_value = [
        {"id": "old", "name": CHARACTER_ENDPOINT_NAME, "createdAt": "2025-01-01"},
        {"id": "new", "name": CHARACTER_ENDPOINT_NAME, "createdAt": "2026-06-01"},
    ]
    assert resolve_character_endpoint_id("key", client=mock) == "new"


def test_resolve_character_endpoint_none() -> None:
    from photoreal.flash.endpoints import EndpointNotFoundError, resolve_character_endpoint_id

    mock = MagicMock()
    mock.get.return_value.status_code = 200
    mock.get.return_value.json.return_value = [{"id": "x", "name": "other"}]
    with pytest.raises(EndpointNotFoundError, match="No Runpod endpoint named"):
        resolve_character_endpoint_id("key", client=mock)


def test_ensure_auto_deploy_then_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    from photoreal.flash import endpoints as ep

    calls = {"n": 0}

    def fake_resolve(
        api_key,
        *,
        preferred_id=None,
        name=ep.CHARACTER_ENDPOINT_NAME,
        log=None,
        client=None,
    ):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ep.EndpointNotFoundError("missing")
        return "ep_new"

    monkeypatch.setattr(ep, "resolve_character_endpoint_id", fake_resolve)
    monkeypatch.setattr(
        "photoreal.flash.deploy.deploy_character_endpoint",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(ep.time, "sleep", lambda s: None)
    eid = ep.ensure_character_endpoint_id("key", preferred_id=None, auto_deploy=True)
    assert eid == "ep_new"
    assert calls["n"] >= 2


def test_flash_scripts_exist() -> None:
    assert Path("scripts/flash_smoke_4090.py").is_file()
    assert Path("scripts/flash_character_endpoint.py").is_file()
    assert Path("scripts/flash_deploy_character.sh").is_file()
    assert Path("scripts/flash_deploy_character.ps1").is_file()
    assert Path("scripts/flash_sync_volume.py").is_file()
    assert Path("scripts/flash_volume_bootstrap.sh").is_file()
    assert Path("scripts/flash_comfyui_extra_model_paths.yaml").is_file()
    assert Path("photoreal/flash/client.py").is_file()
    assert Path("photoreal/flash/endpoints.py").is_file()
    assert Path("photoreal/flash/deploy.py").is_file()
    assert Path("photoreal/flash/volume_sync.py").is_file()
    assert Path("photoreal/flash/volume_layout.py").is_file()


def test_volume_models_complete_detects_gaps(tmp_path: Path) -> None:
    from photoreal.flash.volume_layout import (
        volume_missing_parts,
        volume_models_complete,
    )

    def _sized(path: Path, size: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            if size > 0:
                fh.seek(size - 1)
                fh.write(b"\0")

    assert not volume_models_complete(tmp_path)
    assert volume_missing_parts(tmp_path)

    klein = tmp_path / "data" / "models" / "flux2" / "klein-base-9b"
    loras = tmp_path / "data" / "models" / "loras"
    vlm = tmp_path / "data" / "models" / "vlm" / "Qwen3-VL-8B-Instruct"
    te = klein / "text_encoder"
    tok = klein / "tokenizer"
    for d in (klein, loras, vlm, te, tok):
        d.mkdir(parents=True, exist_ok=True)
    _sized(klein / "ae.safetensors", 100_000_001)
    _sized(klein / "flux-2-klein-base-9b.safetensors", 1_000_000_001)
    _sized(loras / "lenovo_flux_klein9b.safetensors", 1_000_001)
    _sized(loras / "mrpopo_photorealistic.safetensors", 1_000_001)
    for i in range(3):
        (te / f"f{i}.bin").write_text("t", encoding="utf-8")
        (tok / f"t{i}.json").write_text("{}", encoding="utf-8")
    (vlm / "config.json").write_text("{}", encoding="utf-8")
    for i in range(5):
        (vlm / f"w{i}.safetensors").write_bytes(b"y")
    comfy = tmp_path / "runtime" / "comfyui"
    comfy.mkdir(parents=True)
    (comfy / "main.py").write_text("#", encoding="utf-8")
    (tmp_path / "comfyui_extra_model_paths.yaml").write_text("x: 1\n", encoding="utf-8")

    assert volume_models_complete(tmp_path)
    assert volume_missing_parts(tmp_path) == []


def test_volume_sync_needed_respects_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import photoreal.portal.credentials as creds
    import photoreal.flash.volume_sync as vs

    env_path = tmp_path / ".env"
    env_path.write_text(
        "HF_TOKEN=hf\nRUNPOD_API_KEY=rp\nFLASH_VOLUME_SYNCED=1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(creds, "ENV_PATH", env_path)
    assert vs.volume_sync_needed() is False
    assert vs.volume_sync_needed(force=True) is True

    env_path.write_text("HF_TOKEN=hf\nRUNPOD_API_KEY=rp\n", encoding="utf-8")
    assert vs.volume_sync_needed() is True


def test_ensure_network_volume_reuses() -> None:
    from photoreal.flash.volume_layout import VOLUME_DATACENTER, VOLUME_NAME
    from photoreal.flash.volume_sync import ensure_network_volume_id

    mock = MagicMock()
    mock.get.return_value.status_code = 200
    mock.get.return_value.json.return_value = [
        {"id": "vol1", "name": VOLUME_NAME, "dataCenterId": VOLUME_DATACENTER},
    ]
    assert ensure_network_volume_id("key", client=mock) == "vol1"
    mock.post.assert_not_called()


def test_looks_like_no_distro() -> None:
    from photoreal.flash.deploy import WSL_NO_DISTRO_MSG, _looks_like_no_distro

    assert _looks_like_no_distro(
        "Windows Subsystem for Linux has no installed distributions."
    )
    assert not _looks_like_no_distro("Ubuntu\n")
    assert "wsl --install -d Ubuntu" in WSL_NO_DISTRO_MSG


def test_deploy_raises_clear_msg_when_no_wsl_distro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import photoreal.flash.deploy as deploy

    monkeypatch.setattr(deploy.platform, "system", lambda: "Windows")
    monkeypatch.setattr(deploy, "_wsl_exe", lambda: "C:\\Windows\\System32\\wsl.exe")
    monkeypatch.setattr(deploy, "wsl_has_distro", lambda: False)
    monkeypatch.setattr(
        deploy,
        "load_credentials",
        lambda: {"runpod_api_key": "rp", "hf_token": ""},
    )
    monkeypatch.setattr(deploy, "apply_env_to_process", lambda: {})
    with pytest.raises(RuntimeError, match="wsl --install -d Ubuntu"):
        deploy.deploy_character_endpoint()
