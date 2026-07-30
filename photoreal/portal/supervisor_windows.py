"""Windows supervisor: detached processes with logs under data/logs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from photoreal.config import get_settings


def _pid_file(logs_dir: Path, name: str) -> Path:
    return logs_dir / f"{name}.pid"


def _is_pid_running(pid: int) -> bool:
    try:
        # Windows: OpenProcess via tasklist is heavy; use ctypes-free approach
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in r.stdout
    except FileNotFoundError:
        return False


def _read_pid(logs_dir: Path, name: str) -> int | None:
    p = _pid_file(logs_dir, name)
    if not p.is_file():
        return None
    try:
        return int(p.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def _write_pid(logs_dir: Path, name: str, pid: int) -> None:
    _pid_file(logs_dir, name).write_text(str(pid), encoding="utf-8")


def _probe_api() -> bool:
    settings = get_settings()
    import urllib.request

    url = f"http://{settings.api_host}:{settings.api_port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _start_detached(
    cmd: list[str],
    *,
    cwd: Path,
    log_path: Path,
) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
    creationflags = 0x00000200 | 0x00000008
    with open(log_path, "a", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=logf,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    return int(proc.pid)


def start_windows(
    *,
    api_cmd: list[str],
    comfy_cmd: list[str] | None,
    comfy_cwd: Path,
    repo_root: Path,
    logs_dir: Path,
) -> dict[str, Any]:
    logs_dir.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    pids: dict[str, int | None] = {"api": None, "comfy": None}

    if not _probe_api():
        existing = _read_pid(logs_dir, "api")
        if existing and _is_pid_running(existing):
            notes.append(f"api pid {existing} recorded but health failed; starting new")
        pid = _start_detached(
            api_cmd,
            cwd=repo_root,
            log_path=logs_dir / "api.log",
        )
        _write_pid(logs_dir, "api", pid)
        pids["api"] = pid
        notes.append(f"started api pid={pid}")
    else:
        pids["api"] = _read_pid(logs_dir, "api")
        notes.append("api already healthy")

    if comfy_cmd is not None:
        if not comfy_cwd.is_dir():
            raise RuntimeError(f"ComfyUI not found at {comfy_cwd}")
        # stop_comfy() already ran in start_all; just start fresh
        pid = _start_detached(
            comfy_cmd,
            cwd=comfy_cwd,
            log_path=logs_dir / "comfy.log",
        )
        _write_pid(logs_dir, "comfy", pid)
        pids["comfy"] = pid
        notes.append(f"started comfy pid={pid}")

    meta = logs_dir / "supervisor.json"
    meta.write_text(json.dumps({"pids": pids, "notes": notes}, indent=2), encoding="utf-8")
    return {
        "backend": "windows_detached",
        "pids": pids,
        "notes": notes,
        "logs": {
            "api": str(logs_dir / "api.log"),
            "comfy": str(logs_dir / "comfy.log"),
        },
    }
