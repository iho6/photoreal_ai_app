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
    monkeypatch.setattr(env_check, "maybe_ensure_cuda_torch", lambda log=None: False)
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
    monkeypatch.setattr(env_check, "maybe_ensure_cuda_torch", lambda log=None: False)
    with pytest.raises(RuntimeError, match="Runpod Flash"):
        env_check.assert_generate_env()


def test_needs_cuda_torch_reinstall(monkeypatch: pytest.MonkeyPatch) -> None:
    import photoreal.portal.torch_cuda as tc

    monkeypatch.setattr(tc, "nvidia_smi_ok", lambda: False)
    assert tc.needs_cuda_torch_reinstall({"available": False, "cuda_version": None}) is False

    monkeypatch.setattr(tc, "nvidia_smi_ok", lambda: True)
    assert tc.needs_cuda_torch_reinstall({"available": False, "version": "2.x+cpu", "cuda_version": None}) is True
    assert tc.needs_cuda_torch_reinstall({"available": True, "cuda_version": "12.4"}) is True
    assert tc.needs_cuda_torch_reinstall({"available": True, "cuda_version": "12.8"}) is False
    assert (
        tc.needs_cuda_torch_reinstall(
            {"available": True, "version": "2.11.0+cu128", "cuda_version": "12.8"}
        )
        is False
    )


def test_describe_and_format_torch_diag(monkeypatch: pytest.MonkeyPatch) -> None:
    import photoreal.portal.torch_cuda as tc

    info = {
        "available": False,
        "version": "2.6.0+cpu",
        "cuda_version": None,
        "device_count": 0,
        "device_name": None,
        "error": None,
    }
    monkeypatch.setattr(tc, "describe_torch_cuda", lambda: info)
    text = tc.format_torch_diag(info)
    assert "2.6.0+cpu" in text
    assert "available=false" in text


def test_maybe_ensure_skips_when_venv_already_cu128(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import photoreal.portal.env_check as env_check

    ensure_calls = {"n": 0}
    logs: list[str] = []

    monkeypatch.setattr("photoreal.portal.torch_cuda.nvidia_smi_ok", lambda: True)
    monkeypatch.setattr(
        env_check,
        "describe_torch_cuda",
        lambda: {
            "available": False,
            "version": "2.13.0+cpu",
            "cuda_version": None,
            "device_count": 0,
            "device_name": None,
            "error": None,
        },
    )
    monkeypatch.setattr(
        "photoreal.portal.torch_cuda.format_torch_diag",
        lambda info=None: "torch=2.13.0+cpu cuda_build=none available=false gpu=-",
    )
    monkeypatch.setattr(
        "photoreal.portal.torch_cuda.venv_torch_needs_reinstall",
        lambda python=None: (
            False,
            {
                "version": "2.11.0+cu128",
                "cuda_version": "12.8",
                "available": True,
                "error": None,
            },
        ),
    )

    def boom(**kwargs):
        ensure_calls["n"] += 1
        raise AssertionError("ensure_cuda_torch must not run when venv already has cu128")

    monkeypatch.setattr("photoreal.portal.torch_cuda.ensure_cuda_torch", boom)
    env_check.clear_torch_cuda_cache()
    assert env_check.maybe_ensure_cuda_torch(log=logs.append) is True
    assert ensure_calls["n"] == 0
    assert env_check.torch_cuda_available() is True
    assert any("skip reinstall" in line for line in logs)
    assert any("2.11.0+cu128" in line for line in logs)


def test_maybe_ensure_installs_when_venv_still_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import photoreal.portal.env_check as env_check

    ensure_calls = {"n": 0}
    logs: list[str] = []

    monkeypatch.setattr("photoreal.portal.torch_cuda.nvidia_smi_ok", lambda: True)
    monkeypatch.setattr(
        env_check,
        "describe_torch_cuda",
        lambda: {
            "available": False,
            "version": "2.13.0+cpu",
            "cuda_version": None,
            "device_count": 0,
            "device_name": None,
            "error": None,
        },
    )
    monkeypatch.setattr(
        "photoreal.portal.torch_cuda.format_torch_diag",
        lambda info=None: "torch=2.13.0+cpu cuda_build=none available=false gpu=-",
    )
    monkeypatch.setattr(
        "photoreal.portal.torch_cuda.venv_torch_needs_reinstall",
        lambda python=None: (
            True,
            {
                "version": "2.13.0+cpu",
                "cuda_version": None,
                "available": False,
                "error": None,
            },
        ),
    )

    def fake_ensure(**kwargs):
        ensure_calls["n"] += 1
        return True

    monkeypatch.setattr("photoreal.portal.torch_cuda.ensure_cuda_torch", fake_ensure)
    env_check.clear_torch_cuda_cache()
    assert env_check.maybe_ensure_cuda_torch(log=logs.append) is True
    assert ensure_calls["n"] == 1
    assert any("installing cu128" in line for line in logs)


def test_ensure_cuda_torch_uninstalls_then_force_reinstall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import photoreal.portal.torch_cuda as tc

    calls: list[list[str]] = []

    class FakeCompleted:
        def __init__(self, code: int = 0, stdout: str = "", stderr: str = ""):
            self.returncode = code
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        joined = " ".join(cmd)
        if "uninstall" in joined:
            return FakeCompleted(0, stdout="Successfully uninstalled torch")
        if "install" in joined:
            return FakeCompleted(0, stdout="Successfully installed torch-2.7.0+cu128")
        return FakeCompleted(0)

    monkeypatch.setattr(tc, "nvidia_smi_ok", lambda: True)
    monkeypatch.setattr(tc, "needs_cuda_torch_reinstall", lambda info=None: True)
    monkeypatch.setattr(tc.subprocess, "run", fake_run)
    monkeypatch.setattr(
        tc,
        "probe_torch_build_subprocess",
        lambda python=None: {
            "version": "2.7.0+cu128",
            "cuda_version": "12.8",
            "available": True,
            "error": None,
        },
    )
    logs: list[str] = []
    assert tc.ensure_cuda_torch(python="python", log=logs.append, force=True) is True
    assert any("uninstall" in " ".join(c) for c in calls)
    assert any("--force-reinstall" in c for c in calls)
    assert any(tc.CU128_INDEX in c for c in calls)
    assert any("force-installing" in line or "uninstalling" in line for line in logs)


def test_ensure_cuda_torch_rejects_still_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import photoreal.portal.torch_cuda as tc

    class FakeCompleted:
        returncode = 0
        stdout = "Requirement already satisfied: torch"
        stderr = ""

    monkeypatch.setattr(tc, "nvidia_smi_ok", lambda: True)
    monkeypatch.setattr(tc, "needs_cuda_torch_reinstall", lambda info=None: True)
    monkeypatch.setattr(tc.subprocess, "run", lambda *a, **k: FakeCompleted())
    monkeypatch.setattr(
        tc,
        "probe_torch_build_subprocess",
        lambda python=None: {
            "version": "2.13.0+cpu",
            "cuda_version": None,
            "available": False,
            "error": None,
        },
    )
    logs: list[str] = []
    assert tc.ensure_cuda_torch(python="python", log=logs.append, force=True) is False
    assert any("cu128 wheel not installed" in line and "+cpu" in line for line in logs)


def test_looks_like_cpu_and_cu128() -> None:
    from photoreal.portal.torch_cuda import (
        _looks_like_cpu_torch,
        _looks_like_cu128_torch,
    )

    assert _looks_like_cpu_torch("2.13.0+cpu") is True
    assert _looks_like_cu128_torch("2.13.0+cpu", None) is False
    assert _looks_like_cu128_torch("2.7.0+cu128", "12.8") is True
    assert _looks_like_cu128_torch("2.7.0", "12.8") is True
    assert _looks_like_cu128_torch("2.7.0", "12.4") is False


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
    assert Path("scripts/flash_deploy_app.sh").is_file()
    assert Path("scripts/flash_deploy_app.ps1").is_file()
    assert Path("scripts/flash_deploy_character.sh").is_file()
    assert Path("scripts/flash_deploy_character.ps1").is_file()
    assert Path("scripts/flash_sync_volume.py").is_file()
    assert Path("scripts/flash_volume_bootstrap.sh").is_file()
    assert Path("scripts/flash_comfyui_extra_model_paths.yaml").is_file()
    assert Path("flash_apps/README.md").is_file()
    assert Path("flash_apps/character/endpoint.py").is_file()
    assert Path("flash_apps/character/MANIFEST.txt").is_file()
    assert Path("flash_apps/character/META.md").is_file()
    assert Path("flash_apps/wan_animate/META.md").is_file()
    assert Path("flash_apps/_shared/excludes.txt").is_file()
    assert Path("flash_apps/_shared/stage_from_manifest.py").is_file()
    assert Path(".github/workflows/flash-deploy-app.yml").is_file()
    assert Path("photoreal/flash/client.py").is_file()
    assert Path("photoreal/flash/endpoints.py").is_file()
    assert Path("photoreal/flash/deploy.py").is_file()
    assert Path("photoreal/flash/volume_sync.py").is_file()
    assert Path("photoreal/flash/volume_layout.py").is_file()


def test_stage_character_manifest(tmp_path: Path) -> None:
    """Staging copies allowlisted modules and stubs flash/__init__.py."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "stage_from_manifest",
        "flash_apps/_shared/stage_from_manifest.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    app = Path("flash_apps/character")
    # Stage into a temp copy of the app dir so we don't touch the tree permanently
    stage_app = tmp_path / "character"
    stage_app.mkdir()
    for name in ("MANIFEST.txt", "endpoint.py", "META.md"):
        shutil_copy = __import__("shutil").copy2
        shutil_copy(app / name, stage_app / name)

    n = mod.stage(stage_app, repo=Path(".").resolve())
    assert n > 5
    assert (stage_app / "photoreal" / "flash" / "worker_character.py").is_file()
    assert (stage_app / "photoreal" / "flash" / "volume_layout.py").is_file()
    init = (stage_app / "photoreal" / "flash" / "__init__.py").read_text(encoding="utf-8")
    assert "deploy_character" not in init
    assert "gha_deploy" not in init
    # Must not have pulled portal helpers via heavy flash/__init__
    assert not (stage_app / "photoreal" / "flash" / "gha_deploy.py").exists()
    assert not (stage_app / "photoreal" / "portal").exists()


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

    assert not volume_models_complete(tmp_path)
    _sized(te / "qwen_3_8b.safetensors", 1_000_000_001)

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
    from photoreal.flash.volume_sync import ensure_network_volume, ensure_network_volume_id

    mock = MagicMock()
    mock.get.return_value.status_code = 200
    mock.get.return_value.json.return_value = [
        {"id": "vol1", "name": VOLUME_NAME, "dataCenterId": VOLUME_DATACENTER},
    ]
    assert ensure_network_volume_id("key", client=mock) == "vol1"
    vid, dc = ensure_network_volume("key", client=mock)
    assert vid == "vol1"
    assert dc == VOLUME_DATACENTER
    mock.post.assert_not_called()


def test_ensure_network_volume_skips_wrong_dc() -> None:
    """Same name in another DC must not be reused — create in VOLUME_DATACENTER."""
    from photoreal.flash.volume_layout import VOLUME_DATACENTER, VOLUME_NAME
    from photoreal.flash.volume_sync import ensure_network_volume

    mock = MagicMock()
    mock.get.return_value.status_code = 200
    mock.get.return_value.json.return_value = [
        {"id": "old", "name": VOLUME_NAME, "dataCenterId": "US-GA-2"},
    ]
    mock.post.return_value.status_code = 200
    mock.post.return_value.json.return_value = {
        "id": "new",
        "dataCenterId": VOLUME_DATACENTER,
    }
    logs: list[str] = []
    vid, dc = ensure_network_volume("key", client=mock, log=logs.append)
    assert vid == "new"
    assert dc == VOLUME_DATACENTER
    mock.post.assert_called_once()
    body = mock.post.call_args.kwargs.get("json") or mock.post.call_args[1].get("json")
    assert body["dataCenterId"] == VOLUME_DATACENTER
    assert any("ignoring" in m for m in logs)


def test_flash_datacenter_resolves_volume_dc() -> None:
    from photoreal.flash.volume_layout import VOLUME_DATACENTER, flash_datacenter

    dc = flash_datacenter()
    assert getattr(dc, "value", None) == VOLUME_DATACENTER
    assert VOLUME_DATACENTER == "US-CA-2"


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
        lambda: {"runpod_api_key": "rp", "hf_token": "", "github_token": ""},
    )
    monkeypatch.setattr(deploy, "apply_env_to_process", lambda: {})
    with pytest.raises(RuntimeError, match="GitHub Actions|GITHUB_TOKEN"):
        deploy.deploy_character_endpoint()


def test_parse_github_owner_repo() -> None:
    from photoreal.flash.gha_deploy import parse_github_owner_repo

    assert parse_github_owner_repo("git@github.com:acme/photoreal_ai_app.git") == (
        "acme",
        "photoreal_ai_app",
    )
    assert parse_github_owner_repo("https://github.com/acme/photoreal_ai_app.git") == (
        "acme",
        "photoreal_ai_app",
    )


def test_deploy_windows_no_wsl_uses_gha(monkeypatch: pytest.MonkeyPatch) -> None:
    import photoreal.flash.deploy as deploy

    called: dict[str, object] = {}

    def fake_gha(*, github_token: str, log=None, timeout_s: float = 2700.0) -> None:
        called["token"] = github_token
        called["timeout_s"] = timeout_s

    monkeypatch.setattr(deploy.platform, "system", lambda: "Windows")
    monkeypatch.setattr(deploy, "wsl_has_distro", lambda: False)
    monkeypatch.setattr(
        deploy,
        "load_credentials",
        lambda: {
            "runpod_api_key": "rp",
            "hf_token": "hf",
            "github_token": "ghp_test",
        },
    )
    monkeypatch.setattr(deploy, "apply_env_to_process", lambda: {})
    monkeypatch.setattr(
        "photoreal.flash.gha_deploy.deploy_via_github_actions",
        fake_gha,
    )
    deploy.deploy_character_endpoint()
    assert called.get("token") == "ghp_test"


def test_gha_deploy_poll_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from photoreal.flash import gha_deploy as gha

    class FakeResp:
        def __init__(self, status_code: int, data=None, text: str = ""):
            self.status_code = status_code
            self._data = data
            self.text = text

        def json(self):
            return self._data

    calls = {"n": 0}

    class FakeClient:
        def post(self, url, headers=None, json=None):
            assert "dispatches" in url
            assert json and json.get("inputs", {}).get("app") == "character"
            return FakeResp(204)

        def get(self, url, headers=None, params=None):
            calls["n"] += 1
            if "runs/" in url and url.rstrip("/").split("/")[-1].isdigit():
                return FakeResp(
                    200,
                    {
                        "status": "completed",
                        "conclusion": "success",
                        "html_url": "https://github.com/o/r/actions/runs/1",
                    },
                )
            return FakeResp(
                200,
                {
                    "workflow_runs": [
                        {
                            "id": 99,
                            "status": "in_progress",
                            "created_at": "2099-01-01T00:00:00Z",
                            "html_url": "https://github.com/o/r/actions/runs/99",
                        }
                    ]
                },
            )

        def close(self):
            pass

    monkeypatch.setattr(gha.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        "photoreal.portal.credentials.apply_env_to_process",
        lambda: {},
    )
    monkeypatch.setattr(
        "photoreal.portal.credentials.load_credentials",
        lambda: {"runpod_api_key": "rp", "github_token": "tok", "hf_token": "hf"},
    )
    monkeypatch.setattr(
        "photoreal.flash.gha_secrets.try_sync_actions_secrets_from_portal",
        lambda log=None: None,
    )
    gha.deploy_via_github_actions(
        github_token="tok",
        owner="o",
        repo="r",
        ref="main",
        client=FakeClient(),  # type: ignore[arg-type]
        timeout_s=60,
        poll_interval_s=0,
    )
    assert calls["n"] >= 2


def test_gha_deploy_blocks_when_secrets_sync_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from photoreal.flash import gha_deploy as gha

    posted = {"n": 0}

    class FakeClient:
        def post(self, *a, **k):
            posted["n"] += 1
            raise AssertionError("dispatch must not run")

        def close(self):
            pass

    monkeypatch.setattr(
        "photoreal.portal.credentials.apply_env_to_process",
        lambda: {},
    )
    monkeypatch.setattr(
        "photoreal.portal.credentials.load_credentials",
        lambda: {"runpod_api_key": "rp", "github_token": "tok", "hf_token": ""},
    )
    monkeypatch.setattr(
        "photoreal.flash.gha_secrets.try_sync_actions_secrets_from_portal",
        lambda log=None: "No module named 'nacl'",
    )
    with pytest.raises(RuntimeError, match="failed to sync GitHub Actions secrets"):
        gha.deploy_via_github_actions(
            github_token="tok",
            owner="o",
            repo="r",
            ref="main",
            client=FakeClient(),  # type: ignore[arg-type]
        )
    assert posted["n"] == 0


def test_portal_deps_require_nacl() -> None:
    from photoreal.portal.install_probe import PORTAL_MODULES

    assert "nacl" in PORTAL_MODULES


def test_sync_actions_secrets_puts_runpod_and_hf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from photoreal.flash import gha_secrets as gs

    puts: list[str] = []

    class FakeResp:
        def __init__(self, status_code: int, data=None, text: str = ""):
            self.status_code = status_code
            self._data = data or {}
            self.text = text

        def json(self):
            return self._data

    class FakeClient:
        def get(self, url, headers=None):
            assert "public-key" in url
            return FakeResp(200, {"key_id": "kid", "key": "dGVzdA=="})

        def put(self, url, headers=None, json=None):
            name = url.rstrip("/").split("/")[-1]
            puts.append(name)
            assert json and "encrypted_value" in json and json.get("key_id") == "kid"
            return FakeResp(204)

        def close(self):
            pass

    monkeypatch.setattr(gs, "encrypt_secret", lambda key, val: "enc")
    monkeypatch.setattr(gs, "ensure_nacl", lambda log=None: None)
    monkeypatch.setattr(gs, "detect_github_repo", lambda: ("o", "r"))
    gs.sync_actions_secrets(
        github_token="tok",
        runpod_api_key="rp",
        hf_token="hf",
        client=FakeClient(),  # type: ignore[arg-type]
        owner="o",
        repo="r",
    )
    assert puts == ["RUNPOD_API_KEY", "HF_TOKEN"]


def test_sync_actions_secrets_noop_without_token() -> None:
    from photoreal.flash.gha_secrets import sync_actions_secrets

    # Must not raise or call network
    sync_actions_secrets(github_token="", runpod_api_key="rp")
    sync_actions_secrets(github_token="tok", runpod_api_key="")


def test_try_sync_skips_without_creds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import photoreal.portal.credentials as creds
    from photoreal.flash.gha_secrets import try_sync_actions_secrets_from_portal

    env_path = tmp_path / ".env"
    env_path.write_text("HF_TOKEN=hf\n", encoding="utf-8")
    monkeypatch.setattr(creds, "ENV_PATH", env_path)
    assert try_sync_actions_secrets_from_portal() is None
