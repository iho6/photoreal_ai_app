"""Portal credentials, status schema, supervisor dry-run (no network/GPU)."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_portal_extra_in_pyproject() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "portal = [" in text
    assert "fastapi" in text
    assert "pynacl" in text


def test_launch_scripts_probe_nacl() -> None:
    """Stage-1 must reinstall .[portal] when nacl/pynacl is missing."""
    ps1 = Path("scripts/launch.ps1").read_text(encoding="utf-8")
    sh = Path("scripts/launch.sh").read_text(encoding="utf-8")
    assert "portal_deps_satisfied" in ps1
    assert "nacl" in ps1
    assert "portal_deps_satisfied" in sh
    assert "nacl" in sh


def test_launch_scripts_path_preflight() -> None:
    """Stage-1 must validate Python/venv before install and gate the browser on health."""
    ps1 = Path("scripts/launch.ps1").read_text(encoding="utf-8")
    sh = Path("scripts/launch.sh").read_text(encoding="utf-8")
    assert "Test-VenvHealthy" in ps1
    assert "Ensure-HostPython" in ps1
    assert "Python.Python.3.11" in ps1
    assert "did not become healthy" in ps1
    assert "test_venv_healthy" in sh
    assert "ensure_venv" in sh
    assert "did not become healthy" in sh
    assert "WindowsApps" in ps1
    assert "must not leak" in ps1 or "ForEach-Object { Write-Host" in ps1
    for text in (ps1, sh):
        assert "unhealthy:" in text
        assert "removing .venv" in text
        assert "creating .venv with" in text
        assert "recreated OK" in text


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
        runpod_api_key="rp_test_key",
        flash_character_endpoint="ep_test123",
        generate_backend="auto",
        git_user_name="Test User",
        git_user_email="test@example.com",
    )
    assert out["hf_token_set"] is True
    assert out["runpod_token_set"] is True
    assert out["runpod_api_key"] == "rp_test_key"
    assert out["flash_character_endpoint"] == "ep_test123"
    assert env_path.is_file()
    text = env_path.read_text(encoding="utf-8")
    assert "hf_test_token" in text
    assert "RUNPOD_API_KEY=rp_test_key" in text
    assert "FLASH_CHARACTER_ENDPOINT=ep_test123" in text

    # Prefill returns the real local token (length + reveal)
    loaded = creds.load_credentials()
    assert loaded["hf_token_set"] is True
    assert loaded["hf_token"] == "hf_test_token"

    # Bullet placeholder must not wipe existing token
    creds.save_credentials(hf_token="••••••••")
    assert "hf_test_token" in env_path.read_text(encoding="utf-8")


def test_credentials_require_runpod_for_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import photoreal.portal.credentials as creds

    env_path = tmp_path / ".env"
    monkeypatch.setattr(creds, "ENV_PATH", env_path)
    monkeypatch.setattr(creds, "_git_config_get", lambda key: None)
    monkeypatch.setattr(creds, "_git_config_set", lambda key, value: None)

    creds.save_credentials(hf_token="hf_only")
    with pytest.raises(ValueError, match="RUNPOD_API_KEY"):
        creds.assert_launch_credentials()

    creds.save_credentials(runpod_api_key="rp_key")
    tokens = creds.assert_launch_credentials()
    assert tokens["RUNPOD_API_KEY"] == "rp_key"


def test_models_install_satisfied_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import photoreal.portal.install_probe as probe
    import photoreal.portal.paths as paths

    monkeypatch.setattr(probe, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(paths, "REPO_ROOT", tmp_path)
    assert probe.models_install_satisfied() is False

    klein = tmp_path / "data" / "models" / "flux2" / "klein-base-9b"
    loras = tmp_path / "data" / "models" / "loras"
    klein.mkdir(parents=True)
    loras.mkdir(parents=True)
    (klein / "ae.safetensors").write_bytes(b"x" * 100_000_001)
    (klein / "flux-2-klein-base-9b.safetensors").write_bytes(b"x" * 1_000_000_001)
    (loras / "lenovo_flux_klein9b.safetensors").write_bytes(b"x" * 1_000_001)
    (loras / "mrpopo_photorealistic.safetensors").write_bytes(b"x" * 1_000_001)
    te = klein / "text_encoder"
    tok = klein / "tokenizer"
    te.mkdir()
    tok.mkdir()
    for i in range(3):
        (te / f"f{i}.json").write_text("{}", encoding="utf-8")
        (tok / f"t{i}.json").write_text("{}", encoding="utf-8")
    assert probe.models_install_satisfied() is False
    (te / "qwen_3_8b.safetensors").write_bytes(b"x" * 1_000_000_001)
    assert probe.models_install_satisfied() is True


def test_ensure_comfy_extra_local_rewrites_stale_base_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import photoreal.portal.paths as paths

    data = tmp_path / "data"
    data.mkdir()
    local = tmp_path / "comfyui_extra_model_paths.local.yaml"
    local.write_text(
        "photoreal_data:\n  base_path: D:/stale/path/data/\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(paths, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(paths, "COMFY_EXTRA_LOCAL", local)

    logs: list[str] = []
    out = paths.ensure_comfy_extra_local(log=logs.append)
    assert out == local
    text = local.read_text(encoding="utf-8")
    assert "D:/stale" not in text
    assert data.resolve().as_posix() in text.replace("\\", "/")
    assert any("rewrote .local.yaml ->" in m for m in logs)

    # Second call should be a no-op (no new rewrite log).
    logs.clear()
    paths.ensure_comfy_extra_local(log=logs.append)
    assert logs == []


def test_comfy_extra_config_prefers_healed_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import photoreal.portal.paths as paths

    (tmp_path / "data").mkdir()
    local = tmp_path / "comfyui_extra_model_paths.local.yaml"
    monkeypatch.setattr(paths, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(paths, "COMFY_EXTRA_LOCAL", local)
    monkeypatch.setattr(paths, "COMFY_EXTRA", tmp_path / "missing.yaml")

    cfg = paths.comfy_extra_config()
    assert cfg == local
    assert local.is_file()
    assert (tmp_path / "data").resolve().as_posix() in local.read_text(encoding="utf-8")


def test_supervisor_dry_run_commands() -> None:
    from photoreal.portal.supervisor import dry_run_commands

    cmds = dry_run_commands()
    assert "photoreal.portal" in " ".join(cmds["api"])
    assert "main.py" in " ".join(cmds["comfy"])
    assert "8188" in " ".join(cmds["comfy"])
    assert cmds["session"] == "photoreal"


def test_ensure_comfy_reachable_noop_when_up(monkeypatch: pytest.MonkeyPatch) -> None:
    import photoreal.portal.supervisor as sup

    monkeypatch.setattr(
        sup,
        "ensure_repo_comfy",
        lambda **kwargs: {
            "ok": True,
            "restarted": False,
            "reused": True,
            "notes": ["comfy: reusing ours"],
            "comfy_url": "http://127.0.0.1:8188",
            "port": 8188,
            "health": {},
            "logs": {"comfy": "x"},
            "error": None,
        },
    )
    out = sup.ensure_comfy_reachable()
    assert out["ok"] is True
    assert out["reused"] is True


def test_ensure_comfy_reachable_restarts_when_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import photoreal.portal.supervisor as sup

    monkeypatch.setattr(
        sup,
        "ensure_repo_comfy",
        lambda **kwargs: {
            "ok": True,
            "restarted": True,
            "reused": False,
            "notes": ["comfy: started"],
            "health": {},
            "logs": {"comfy": "x"},
            "error": None,
            "port": 8188,
            "comfy_url": "http://127.0.0.1:8188",
        },
    )
    out = sup.ensure_comfy_reachable()
    assert out["ok"] is True
    assert out["restarted"] is True


def test_restart_comfy_force_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    import photoreal.portal.supervisor as sup

    seen: dict = {}

    def fake_ensure(**kwargs):
        seen.update(kwargs)
        return {
            "ok": True,
            "restarted": True,
            "reused": False,
            "notes": ["forced"],
            "health": {},
            "logs": {},
            "error": None,
            "port": 8188,
            "comfy_url": "http://127.0.0.1:8188",
        }

    monkeypatch.setattr(sup, "ensure_repo_comfy", fake_ensure)
    out = sup.restart_comfy(timeout=5.0)
    assert out["ok"] is True
    assert seen.get("force") is True


def test_is_our_comfy_pid_by_cmdline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import photoreal.portal.comfy_ownership as own
    import photoreal.portal.paths as paths

    monkeypatch.setattr(own, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(own, "COMFY_DIR", tmp_path / "runtime" / "comfyui")
    monkeypatch.setattr(own, "LOGS_DIR", tmp_path / "data" / "logs")
    (tmp_path / "data" / "logs").mkdir(parents=True)
    (tmp_path / "runtime" / "comfyui").mkdir(parents=True)

    ours_cmd = (
        f'"{tmp_path / "runtime" / "python" / "python.exe"}" '
        f'main.py --listen 127.0.0.1 --port 8188 '
        f'--extra-model-paths-config "{tmp_path / "comfyui_extra_model_paths.local.yaml"}"'
    )
    # Place COMFY_DIR in cmdline the way Windows does (cwd is comfyui).
    ours_cmd = str(tmp_path / "runtime" / "comfyui") + " " + ours_cmd
    assert own.is_our_comfy_pid(12345, cmdline=ours_cmd) is True
    alien = r'C:\other\repo\runtime\comfyui\python.exe main.py --port 8188'
    assert own.is_our_comfy_pid(999, cmdline=alien) is False


def test_ensure_repo_comfy_reuses_ours(monkeypatch: pytest.MonkeyPatch) -> None:
    import photoreal.portal.supervisor as sup

    monkeypatch.setattr(sup, "classify_port", lambda port=8188: "ours")
    monkeypatch.setattr(sup, "comfy_system_stats_ok", lambda url: True)
    monkeypatch.setattr(sup, "comfy_photoreal_models_ready", lambda url: (True, []))
    monkeypatch.setattr(sup, "set_session_comfy_url", lambda url: url)
    started = {"n": 0}
    monkeypatch.setattr(
        sup,
        "_start_comfy_process",
        lambda **kwargs: started.__setitem__("n", started["n"] + 1) or {},
    )
    monkeypatch.setattr(sup, "health_snapshot", lambda: {})
    out = sup.ensure_repo_comfy(force=False)
    assert out["ok"] is True
    assert out["reused"] is True
    assert started["n"] == 0


def test_ensure_repo_comfy_alien_uses_alt_port(monkeypatch: pytest.MonkeyPatch) -> None:
    import photoreal.portal.supervisor as sup

    monkeypatch.setattr(sup, "classify_port", lambda port=8188: "alien")
    monkeypatch.setattr(sup, "find_free_comfy_port", lambda **kwargs: 8189)
    monkeypatch.setattr(sup, "set_session_comfy_url", lambda url: url)
    monkeypatch.setattr(sup, "torch_cuda_available", lambda: True)
    started: dict = {}

    def fake_start(*, emit=None, port=None):
        started["port"] = port
        return {"notes": ["started"], "port": port}

    monkeypatch.setattr(sup, "_start_comfy_process", fake_start)
    monkeypatch.setattr(sup, "wait_for_comfy", lambda **kwargs: True)
    monkeypatch.setattr(sup, "comfy_photoreal_models_ready", lambda url: (True, []))
    monkeypatch.setattr(sup, "health_snapshot", lambda: {})
    monkeypatch.setattr(sup, "stop_our_comfy", lambda **kwargs: {"notes": [], "killed": []})

    out = sup.ensure_repo_comfy(force=False)
    assert out["ok"] is True
    assert started.get("port") == 8189
    assert out["port"] == 8189
    assert "8189" in (out.get("comfy_url") or "")


def test_assert_generate_env_heals_comfy_when_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import photoreal.portal.credentials as creds
    import photoreal.portal.env_check as env_check
    import photoreal.flash.backend as backend
    import photoreal.portal.install_probe as probe

    env_path = tmp_path / ".env"
    env_path.write_text(
        "HF_TOKEN=hf\nGENERATE_BACKEND=local\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(creds, "ENV_PATH", env_path)
    monkeypatch.setattr(backend, "torch_cuda_available", lambda: True)
    monkeypatch.setattr(env_check, "maybe_ensure_cuda_torch", lambda log=None: True)
    monkeypatch.setattr(probe, "models_install_satisfied", lambda: True)
    monkeypatch.setattr(probe, "models_missing_parts", lambda: [])

    vlm = tmp_path / "vlm"
    vlm.mkdir()
    monkeypatch.setattr(env_check, "vlm_model_path", lambda: vlm)

    monkeypatch.setattr(
        env_check,
        "comfy_reachable",
        lambda timeout=2.0, base_url=None: True,
    )
    monkeypatch.setattr(
        "photoreal.portal.supervisor.ensure_repo_comfy",
        lambda emit=None, timeout=180.0, force=False: {
            "ok": True,
            "notes": ["comfy: reusing ours on 8188"],
            "logs": {"comfy": "log"},
            "comfy_url": "http://127.0.0.1:8188",
            "port": 8188,
            "reused": True,
        },
    )
    logs: list[str] = []
    info = env_check.assert_generate_env(log=logs.append, heal_cuda=False)
    assert info["backend"] == "local"
    assert info["comfy_ok"] is True
    assert any("ensuring this repo" in line or "reusing" in line for line in logs)


def test_comfy_reachable_passes_base_url_to_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import photoreal.portal.env_check as env_check

    seen: dict[str, str] = {}

    class FakeClient:
        def __init__(self, base_url: str) -> None:
            seen["base_url"] = base_url

        def health(self) -> bool:
            return True

    monkeypatch.setattr(
        "photoreal.services.comfy_client.ComfyClient",
        FakeClient,
    )
    assert env_check.comfy_reachable(base_url="http://127.0.0.1:8189/") is True
    assert seen["base_url"] == "http://127.0.0.1:8189"


def test_assert_generate_env_fails_when_weights_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import photoreal.portal.credentials as creds
    import photoreal.portal.env_check as env_check
    import photoreal.flash.backend as backend
    import photoreal.portal.install_probe as probe

    env_path = tmp_path / ".env"
    env_path.write_text(
        "HF_TOKEN=hf\nGENERATE_BACKEND=local\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(creds, "ENV_PATH", env_path)
    monkeypatch.setattr(backend, "torch_cuda_available", lambda: True)
    monkeypatch.setattr(env_check, "maybe_ensure_cuda_torch", lambda log=None: True)
    monkeypatch.setattr(probe, "models_install_satisfied", lambda: False)
    monkeypatch.setattr(
        probe,
        "models_missing_parts",
        lambda: ["missing/small: data/models/flux2/klein-base-9b/text_encoder/qwen_3_8b.safetensors"],
    )
    ensured = {"n": 0}

    def fake_ensure(**kwargs):
        ensured["n"] += 1
        return {"ok": True, "notes": [], "logs": {}}

    monkeypatch.setattr("photoreal.portal.supervisor.ensure_repo_comfy", fake_ensure)

    with pytest.raises(RuntimeError, match="qwen_3_8b|photoreal weights incomplete"):
        env_check.assert_generate_env(heal_cuda=False)
    assert ensured["n"] == 0


def test_should_skip_local_model_download() -> None:
    from photoreal.portal.bootstrap import should_skip_local_model_download

    assert should_skip_local_model_download(runpod_token_set=True, nvidia_ok=False) is True
    assert should_skip_local_model_download(runpod_token_set=True, nvidia_ok=True) is False
    assert should_skip_local_model_download(runpod_token_set=False, nvidia_ok=False) is False
    assert should_skip_local_model_download(runpod_token_set=False, nvidia_ok=True) is False


def test_launch_model_download_argv_is_photoreal_and_vlm_not_all() -> None:
    from photoreal.portal.bootstrap import (
        LAUNCH_DOWNLOAD_FLAGS,
        launch_model_download_argv,
    )

    argv = launch_model_download_argv("python")
    assert argv[0] == "python"
    assert argv[-2:] == list(LAUNCH_DOWNLOAD_FLAGS)
    assert "--photoreal-gen" in argv
    assert "--vlm" in argv
    assert "--all" not in argv
    text = Path("photoreal/portal/bootstrap.py").read_text(encoding="utf-8")
    assert '"--all"' not in text and "'--all'" not in text
    assert "Download models (photoreal-gen + vlm)" in text


def test_launch_model_download_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import photoreal.portal.bootstrap as boot
    import photoreal.portal.install_probe as probe

    monkeypatch.setattr(boot, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(probe, "models_install_satisfied", lambda: False)
    monkeypatch.setattr(boot, "models_install_satisfied", lambda: False)
    assert boot.launch_model_download_needed() is True

    monkeypatch.setattr(probe, "models_install_satisfied", lambda: True)
    monkeypatch.setattr(boot, "models_install_satisfied", lambda: True)
    assert boot.launch_model_download_needed() is True  # VLM still missing

    vlm = tmp_path / "data" / "models" / "vlm" / "Qwen3-VL-8B-Instruct"
    vlm.mkdir(parents=True)
    (vlm / "config.json").write_text("{}", encoding="utf-8")
    assert boot.vlm_weights_present() is True
    assert boot.launch_model_download_needed() is False


def test_models_missing_parts_lists_qwen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import photoreal.portal.install_probe as probe

    monkeypatch.setattr(probe, "REPO_ROOT", tmp_path)
    gaps = probe.models_missing_parts()
    assert any("qwen_3_8b" in g for g in gaps)
    assert probe.models_install_satisfied() is False


def test_portal_app_status_and_health() -> None:
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from photoreal.portal.app import create_app

    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert isinstance(r.json().get("build"), str) and r.json()["build"]

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

    timeline = client.get("/timeline")
    assert timeline.status_code == 200
    assert b"timeline" in timeline.content.lower()

    character = client.get("/character")
    assert character.status_code == 200
    assert b"character" in character.content.lower()

    bad = client.post("/api/character/generate", json={"prompt": ""})
    assert bad.status_code == 422

    gal = client.get("/api/character/gallery")
    assert gal.status_code == 200
    assert "items" in gal.json()
    assert isinstance(gal.json()["items"], list)

    missing = client.get("/api/character/jobs/does-not-exist")
    assert missing.status_code == 404


def test_portal_shells_inject_build_and_no_store() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from photoreal.portal.app import create_app

    client = TestClient(create_app())
    build = client.get("/api/health").json()["build"]
    assert build and "__BUILD__" not in build

    for path in ("/", "/timeline", "/character"):
        r = client.get(path)
        assert r.status_code == 200, path
        cc = r.headers.get("cache-control", "")
        assert "no-store" in cc.lower(), (path, cc)
        text = r.text
        assert "__BUILD__" not in text, path
        assert f'content="{build}"' in text, path
        assert f"?v={build}" in text, path
        assert "/ui/build_guard.js" in text, path


def test_project_roundtrip_media_and_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from photoreal.portal import project_store
    from photoreal.portal.app import create_app

    project_dir = tmp_path / "default"
    media_dir = project_dir / "media"
    project_json = project_dir / "project.json"
    media_dir.mkdir(parents=True)

    monkeypatch.setattr(project_store, "PROJECTS_ROOT", tmp_path)
    monkeypatch.setattr(project_store, "PROJECT_DIR", project_dir)
    monkeypatch.setattr(project_store, "MEDIA_DIR", media_dir)
    monkeypatch.setattr(project_store, "PROJECT_JSON", project_json)

    client = TestClient(create_app())
    fake = b"FAKEWEBM_BYTES_FOR_TEST"
    up = client.post(
        "/api/project/media",
        files={"file": ("reference.webm", fake, "video/webm")},
    )
    assert up.status_code == 200, up.text
    body = up.json()
    assert body["url"].startswith("/project-media/")
    assert body["url"].endswith(".webm")
    assert (media_dir / body["filename"]).read_bytes() == fake

    doc = {
        "version": 1,
        "timeline": {
            "fps": 30,
            "pxPerSec": 80,
            "playhead": 0,
            "snap": True,
            "tracks": [
                {
                    "id": "trk_ref",
                    "name": "References",
                    "locked": False,
                    "hidden": False,
                    "height": 64,
                }
            ],
            "clips": [
                {
                    "id": "clip_ref",
                    "trackId": "trk_ref",
                    "name": "Reference 1",
                    "mediaType": "video",
                    "src": body["url"],
                    "start": 0,
                    "duration": 2.5,
                    "inPoint": 0,
                    "sourceDuration": 2.5,
                    "role": "reference",
                    "refSlot": 1,
                }
            ],
            "selection": None,
        },
        "characters": {"usedUrls": []},
    }
    put = client.put("/api/project", json=doc)
    assert put.status_code == 200, put.text
    assert project_json.is_file()

    got = client.get("/api/project")
    assert got.status_code == 200
    loaded = got.json()
    assert loaded["timeline"]["tracks"]
    assert loaded["timeline"]["clips"][0]["src"] == body["url"]

    media = client.get(body["url"])
    assert media.status_code == 200
    assert media.content == fake
