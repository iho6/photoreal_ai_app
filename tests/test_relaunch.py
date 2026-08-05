"""Install probe + stamp helpers (no network/pip)."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_requirements_sha_and_stamp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import photoreal.portal.install_probe as probe

    req = tmp_path / "comfyui-photoreal.txt"
    req.write_text("aiohttp\neinops\n", encoding="utf-8")
    stamp_dir = tmp_path / "logs"
    stamp_dir.mkdir()
    stamp = stamp_dir / "comfy_reqs.sha256"

    monkeypatch.setattr(probe, "COMFY_REQUIREMENTS", req)
    monkeypatch.setattr(probe, "COMFY_STAMP", stamp)
    monkeypatch.setattr(probe, "LOGS_DIR", stamp_dir)
    monkeypatch.setattr(probe, "torch_cuda_flavor", lambda: "cpu")

    digest = probe.requirements_sha256(req)
    assert len(digest) == 64
    assert not probe.comfy_stamp_matches(req)

    probe.write_comfy_stamp(req)
    assert stamp.is_file()
    text = stamp.read_text(encoding="utf-8")
    assert "cpu" in text
    assert probe.comfy_stamp_matches(req)

    req.write_text("aiohttp\neinops\nsafetensors\n", encoding="utf-8")
    assert not probe.comfy_stamp_matches(req)


def test_modules_importable_stdlib() -> None:
    from photoreal.portal.install_probe import modules_importable

    assert modules_importable(("json", "hashlib")) is True
    assert modules_importable(("json", "definitely_missing_mod_xyz")) is False


def test_comfy_install_satisfied_ignores_sticky_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Portal in-process +cpu must not force Launch to reinstall every time."""
    import photoreal.portal.install_probe as probe

    monkeypatch.setattr(probe, "comfy_stamp_matches", lambda path=None: True)
    monkeypatch.setattr(probe, "comfy_probe_satisfied", lambda: True)
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
    assert probe.comfy_install_satisfied() is True

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
    assert probe.comfy_install_satisfied() is False


def test_bootstrap_install_comfy_skips_force_when_venv_cu128() -> None:
    """Post-pip path must gate force=True on venv probe, not always reinstall."""
    text = Path("photoreal/portal/bootstrap.py").read_text(encoding="utf-8")
    assert "venv_torch_needs_reinstall" in text
    assert "still cu128 after requirements — skip force reinstall" in text
    assert "force=True" in text  # still used when venv needs heal
    # Must not unconditionally force after pip -r without a needs_after check.
    assert "needs_after" in text


def test_ensure_cuda_torch_skip_uses_venv_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import photoreal.portal.torch_cuda as tc

    run_calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        run_calls.append(list(cmd))

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    monkeypatch.setattr(tc, "nvidia_smi_ok", lambda: True)
    monkeypatch.setattr(
        tc,
        "venv_torch_needs_reinstall",
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
    monkeypatch.setattr(tc.subprocess, "run", fake_run)
    logs: list[str] = []
    assert tc.ensure_cuda_torch(python="python", log=logs.append, force=False) is True
    assert not any("uninstall" in " ".join(c) for c in run_calls)
    assert any("already OK" in line for line in logs)


def test_ports_kill_skips_keep_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    from photoreal.portal import ports

    monkeypatch.setattr(ports, "pids_listening_on", lambda port: [111, 222])
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(ports.subprocess, "run", fake_run)
    killed = ports.kill_pids([111, 222], keep_pid=111)
    assert killed == [222]
    assert any("222" in " ".join(c) or c[-1] == "222" for c in calls)


def test_force_launch_replaces_running(monkeypatch: pytest.MonkeyPatch) -> None:
    import photoreal.portal.bootstrap as boot

    # Reset state
    boot.cancel_launch(timeout=1.0)
    with boot.STATE._cond:
        boot.STATE.running = False
        boot.STATE.finished = False
        boot.STATE.generation = 0
        boot.STATE.lines.clear()
        boot.STATE.cancel.clear()

    started: list[int] = []

    def fake_stage2(*, emit=None, cancel=None, generation=None):
        started.append(generation or 0)
        # Simulate long work until cancelled or short sleep
        for _ in range(50):
            if cancel is not None and cancel.is_set():
                raise boot.LaunchCancelled("stopped")
            if generation is not None and generation != boot.STATE.generation:
                raise boot.LaunchCancelled("replaced")
            import time

            time.sleep(0.05)

    monkeypatch.setattr(boot, "run_stage2", fake_stage2)
    r1 = boot.start_launch_async(force=True)
    assert r1["started"] is True
    import time

    time.sleep(0.1)
    r2 = boot.start_launch_async(force=True)
    assert r2["started"] is True
    assert r2["replaced"] is True
    time.sleep(0.3)
    assert boot.STATE.running is False or boot.STATE.generation >= 2
