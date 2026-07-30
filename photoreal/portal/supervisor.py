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
    return [
        py,
        "main.py",
        "--listen",
        "127.0.0.1",
        "--port",
        str(COMFY_PORT),
        "--extra-model-paths-config",
        str(extra.resolve()),
    ]


def _probe(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, ValueError):
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


def start_all(*, ensure_comfy: bool = True) -> dict[str, Any]:
    """Start/restart long-running services. Returns status dict."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []

    stop_info = stop_comfy()
    notes.extend(stop_info.get("notes") or [])

    system = platform.system().lower()
    if system == "linux":
        from photoreal.portal.supervisor_linux import start_linux

        result = start_linux(
            api_cmd=api_command(),
            comfy_cmd=comfy_command() if ensure_comfy else None,
            comfy_cwd=COMFY_DIR,
            repo_root=REPO_ROOT,
        )
    elif system == "windows":
        from photoreal.portal.supervisor_windows import start_windows

        result = start_windows(
            api_cmd=api_command(),
            comfy_cmd=comfy_command() if ensure_comfy else None,
            comfy_cwd=COMFY_DIR,
            repo_root=REPO_ROOT,
            logs_dir=LOGS_DIR,
        )
    else:
        if shutil.which("tmux"):
            from photoreal.portal.supervisor_linux import start_linux

            result = start_linux(
                api_cmd=api_command(),
                comfy_cmd=comfy_command() if ensure_comfy else None,
                comfy_cwd=COMFY_DIR,
                repo_root=REPO_ROOT,
            )
        else:
            raise RuntimeError(
                f"Unsupported platform {system!r}: install tmux or use Linux/Windows launchers"
            )
    result["notes"] = list(notes) + list(result.get("notes") or [])
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
