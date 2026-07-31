"""Service supervisor — start/stop API + Comfy (OS-specific backends)."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any

from photoreal.config import get_settings
from photoreal.portal.env_check import torch_cuda_available
from photoreal.portal.paths import (
    COMFY_DIR,
    LOGS_DIR,
    REPO_ROOT,
    comfy_extra_config,
    venv_python,
)
from photoreal.portal.ports import free_port

TMUX_SESSION = "photoreal"
API_PORT = 8010
COMFY_PORT = 8188


def api_command() -> list[str]:
    settings = get_settings()
    py = str(venv_python())
    return [
        py,
        "-m",
        "photoreal.portal",
        "--host",
        settings.api_host,
        "--port",
        str(settings.api_port),
    ]


def comfy_command() -> list[str]:
    py = str(venv_python())
    extra = comfy_extra_config()
    cmd = [
        py,
        "main.py",
        "--listen",
        "127.0.0.1",
        "--port",
        str(COMFY_PORT),
        "--extra-model-paths-config",
        str(extra.resolve()),
    ]
    # ComfyUI crashes on import when torch is CPU-only unless --cpu is set.
    if not torch_cuda_available():
        cmd.append("--cpu")
    return cmd


def _probe(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def wait_for_comfy(
    *,
    timeout: float = 90.0,
    interval: float = 1.0,
    emit: Any | None = None,
) -> bool:
    """Poll Comfy ``/system_stats`` until up or timeout."""
    import time

    def _emit(msg: str) -> None:
        if emit:
            try:
                emit(msg)
            except Exception:  # noqa: BLE001
                pass

    settings = get_settings()
    url = f"{settings.comfy_url.rstrip('/')}/system_stats"
    deadline = time.monotonic() + timeout
    started = time.monotonic()
    last_note = -999.0
    while time.monotonic() < deadline:
        if _probe(url, timeout=min(2.0, interval)):
            return True
        elapsed = time.monotonic() - started
        if elapsed - last_note >= 10.0:
            _emit(f"waiting for Comfy… {elapsed:.0f}s / {timeout:.0f}s")
            last_note = elapsed
        time.sleep(interval)
    return False


def health_snapshot() -> dict[str, Any]:
    settings = get_settings()
    api_url = f"http://{settings.api_host}:{settings.api_port}/api/health"
    comfy_url = f"{settings.comfy_url.rstrip('/')}/system_stats"
    return {
        "api": {"url": api_url, "ok": _probe(api_url)},
        "comfy": {"url": comfy_url, "ok": _probe(comfy_url)},
        "platform": platform.system().lower(),
        "tmux_session": TMUX_SESSION if platform.system().lower() == "linux" else None,
        "logs_dir": str(LOGS_DIR),
        "torch_cuda": torch_cuda_available(),
    }


def stop_comfy() -> dict[str, Any]:
    """Stop Comfy listeners on 8188 (PID file + port). Safe during Stage-2."""
    notes: list[str] = []
    system = platform.system().lower()

    pid_path = LOGS_DIR / "comfy.pid"
    if pid_path.is_file():
        try:
            old = int(pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            old = None
        if old:
            if system == "windows":
                subprocess.run(
                    ["taskkill", "/PID", str(old), "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                subprocess.run(
                    ["kill", "-TERM", str(old)], capture_output=True, check=False
                )
            notes.append(f"stopped comfy pid file {old}")
        try:
            pid_path.unlink(missing_ok=True)
        except OSError:
            pass

    if system == "linux" and shutil.which("tmux"):
        subprocess.run(
            ["tmux", "kill-window", "-t", f"{TMUX_SESSION}:comfy"],
            capture_output=True,
            check=False,
        )
        notes.append("killed tmux comfy window (if present)")

    killed = free_port(COMFY_PORT)
    if killed:
        notes.append(f"freed port {COMFY_PORT}: killed {killed}")
    else:
        notes.append(f"port {COMFY_PORT} clear")
    return {"notes": notes, "killed": killed}


def stop_stale_api(*, keep_pid: int | None = None) -> dict[str, Any]:
    """Free API port unless the listener is ``keep_pid`` (current portal)."""
    if keep_pid is None:
        keep_pid = os.getpid()
    settings = get_settings()
    port = int(settings.api_port)
    killed = free_port(port, keep_pid=keep_pid)
    return {
        "notes": (
            [f"freed port {port}: killed {killed}"]
            if killed
            else [f"port {port} ok"]
        ),
        "killed": killed,
    }


def start_all(
    *,
    ensure_comfy: bool = True,
    emit: Any | None = None,
) -> dict[str, Any]:
    """Start/restart long-running services. Returns status dict."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []

    def _note(msg: str) -> None:
        notes.append(msg)
        if emit:
            try:
                emit(msg)
            except Exception:  # noqa: BLE001
                pass

    stop_info = stop_comfy()
    for n in stop_info.get("notes") or []:
        _note(str(n))

    # Local Comfy is only needed for local CUDA generate. With Runpod configured
    # and no CUDA, skip starting CPU Comfy (avoids long boot + 180s health wait).
    skip_comfy = False
    if ensure_comfy:
        try:
            from photoreal.portal.credentials import apply_env_to_process, load_credentials

            apply_env_to_process()
            creds = load_credentials()
            has_runpod = bool(creds.get("runpod_token_set"))
            backend = (creds.get("generate_backend") or "auto").strip().lower()
            # Prefer Flash path when Runpod is set and we are not forcing local,
            # without importing torch unless necessary.
            if has_runpod and backend != "local":
                if not torch_cuda_available():
                    skip_comfy = True
                    _note(
                        "skip local Comfy (no CUDA; Runpod Flash configured for generate)"
                    )
        except Exception as exc:  # noqa: BLE001
            _note(f"Runpod probe skipped ({exc}); starting local Comfy with --cpu")

    want_comfy = ensure_comfy and not skip_comfy
    system = platform.system().lower()
    if system == "linux":
        from photoreal.portal.supervisor_linux import start_linux

        result = start_linux(
            api_cmd=api_command(),
            comfy_cmd=comfy_command() if want_comfy else None,
            comfy_cwd=COMFY_DIR,
            repo_root=REPO_ROOT,
        )
    elif system == "windows":
        from photoreal.portal.supervisor_windows import start_windows

        result = start_windows(
            api_cmd=api_command(),
            comfy_cmd=comfy_command() if want_comfy else None,
            comfy_cwd=COMFY_DIR,
            repo_root=REPO_ROOT,
            logs_dir=LOGS_DIR,
        )
    else:
        if shutil.which("tmux"):
            from photoreal.portal.supervisor_linux import start_linux

            result = start_linux(
                api_cmd=api_command(),
                comfy_cmd=comfy_command() if want_comfy else None,
                comfy_cwd=COMFY_DIR,
                repo_root=REPO_ROOT,
            )
        else:
            raise RuntimeError(
                f"Unsupported platform {system!r}: install tmux or use Linux/Windows launchers"
            )
    for n in result.get("notes") or []:
        _note(str(n))
    result["notes"] = list(notes)
    if want_comfy:
        if not torch_cuda_available():
            _note("Comfy started with --cpu (PyTorch has no CUDA on this machine)")
        _note("waiting for Comfy /system_stats…")
        # First boot can spend >90s on SQLite asset migrations + imports.
        if wait_for_comfy(timeout=180.0, emit=emit):
            _note("Comfy is healthy")
        else:
            _note(
                f"Comfy did not become healthy within 180s — see {LOGS_DIR / 'comfy.log'}"
            )
    result["health"] = health_snapshot()
    return result


def dry_run_commands() -> dict[str, Any]:
    """For tests — command lines without starting processes."""
    return {
        "api": api_command(),
        "comfy": comfy_command(),
        "comfy_cwd": str(COMFY_DIR),
        "session": TMUX_SESSION,
        "platform": platform.system().lower(),
        "ports": {"api": API_PORT, "comfy": COMFY_PORT},
    }
