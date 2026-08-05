"""Detect whether a ComfyUI listener belongs to this repo (vs alien / stale)."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Literal

from photoreal.portal.paths import COMFY_DIR, LOGS_DIR, REPO_ROOT
from photoreal.portal.ports import pids_listening_on

PortClass = Literal["empty", "ours", "alien"]

PREFERRED_COMFY_PORT = 8188
COMFY_PORT_SPAN = 12

PHOTOREAL_COMFY_MODELS = (
    "flux-2-klein-base-9b.safetensors",
    "ae.safetensors",
    "qwen_3_8b.safetensors",
    "lenovo_flux_klein9b.safetensors",
    "mrpopo_photorealistic.safetensors",
)


def _norm_path(p: str | Path) -> str:
    try:
        return str(Path(p).resolve()).replace("\\", "/").casefold()
    except OSError:
        return str(p).replace("\\", "/").casefold()


def process_cmdline(pid: int) -> str:
    """Return the process command line for ``pid`` (empty if unavailable)."""
    if pid <= 0:
        return ""
    system = platform.system().lower()
    if system == "windows":
        try:
            r = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=8,
            )
            return (r.stdout or "").strip()
        except (OSError, subprocess.TimeoutExpired):
            return ""
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode(
            "utf-8", errors="replace"
        )
    except OSError:
        return ""


def read_comfy_pidfile() -> int | None:
    path = LOGS_DIR / "comfy.pid"
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def is_our_comfy_pid(pid: int, *, cmdline: str | None = None) -> bool:
    """True if ``pid`` looks like this repo's ComfyUI ``main.py`` process."""
    if pid <= 0:
        return False
    recorded = read_comfy_pidfile()
    if recorded is not None and recorded == pid:
        return True
    cmd = cmdline if cmdline is not None else process_cmdline(pid)
    if not cmd:
        return False
    low = cmd.replace("\\", "/").casefold()
    if "main.py" not in low:
        return False
    comfy_marker = _norm_path(COMFY_DIR)
    repo_marker = _norm_path(REPO_ROOT)
    return comfy_marker in low or (
        repo_marker in low and ("comfyui" in low or "photoreal" in low)
    )


def classify_port(port: int = PREFERRED_COMFY_PORT) -> PortClass:
    """Classify listeners on ``port`` as empty, ours, or alien."""
    pids = pids_listening_on(port)
    if not pids:
        return "empty"
    ours = any(is_our_comfy_pid(pid) for pid in pids)
    if ours:
        return "ours"
    return "alien"


def comfy_base_url(port: int) -> str:
    return f"http://127.0.0.1:{int(port)}"


def set_session_comfy_url(url: str) -> str:
    """Point this portal process at ``url`` for subsequent ``get_settings()`` calls."""
    cleaned = url.rstrip("/")
    os.environ["COMFY_URL"] = cleaned
    return cleaned


def session_comfy_url() -> str:
    return (os.environ.get("COMFY_URL") or comfy_base_url(PREFERRED_COMFY_PORT)).rstrip(
        "/"
    )


def find_free_comfy_port(
    *,
    preferred: int = PREFERRED_COMFY_PORT,
    span: int = COMFY_PORT_SPAN,
) -> int:
    """
    Pick a free listen port for our Comfy.

    Prefer ``preferred`` when empty. If alien owns preferred, skip to preferred+1…
    """
    for offset in range(span):
        port = preferred + offset
        if offset == 0:
            kind = classify_port(port)
            if kind == "empty":
                return port
            if kind == "ours":
                return port
            continue
        if not pids_listening_on(port):
            return port
    raise RuntimeError(
        f"No free Comfy port in {preferred}–{preferred + span - 1} "
        f"(preferred {preferred} held by another process)"
    )


def _object_info_blob(base_url: str, *, timeout: float = 8.0) -> str:
    url = f"{base_url.rstrip('/')}/object_info"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read()
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return ""
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def comfy_photoreal_models_ready(
    base_url: str,
    *,
    required: tuple[str, ...] = PHOTOREAL_COMFY_MODELS,
) -> tuple[bool, list[str]]:
    """
    True when Comfy ``/object_info`` lists the photoreal workflow weight names.

    Returns ``(ok, missing_or_reasons)``.
    """
    blob = _object_info_blob(base_url)
    if not blob:
        return False, ["object_info unreachable"]
    missing = [name for name in required if name not in blob]
    return (not missing), missing


def comfy_system_stats_ok(base_url: str, *, timeout: float = 2.0) -> bool:
    url = f"{base_url.rstrip('/')}/system_stats"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False


def describe_port(port: int = PREFERRED_COMFY_PORT) -> dict[str, Any]:
    """Debug snapshot for logs/tests."""
    pids = pids_listening_on(port)
    return {
        "port": port,
        "class": classify_port(port),
        "pids": pids,
        "cmdlines": {pid: process_cmdline(pid)[:200] for pid in pids},
        "pidfile": read_comfy_pidfile(),
    }
