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
from photoreal.portal.comfy_ownership import (
    PREFERRED_COMFY_PORT,
    classify_port,
    comfy_base_url,
    comfy_photoreal_models_ready,
    comfy_system_stats_ok,
    find_free_comfy_port,
    is_our_comfy_pid,
    process_cmdline,
    set_session_comfy_url,
)
from photoreal.portal.env_check import torch_cuda_available
from photoreal.portal.paths import (
    COMFY_DIR,
    LOGS_DIR,
    REPO_ROOT,
    comfy_extra_config,
    ensure_comfy_extra_local,
    venv_python,
)
from photoreal.portal.ports import free_port, kill_pids, pids_listening_on

TMUX_SESSION = "photoreal"
API_PORT = 8010
COMFY_PORT = PREFERRED_COMFY_PORT


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


def comfy_command(*, port: int | None = None) -> list[str]:
    py = str(venv_python())
    extra = comfy_extra_config()
    listen_port = int(port) if port is not None else COMFY_PORT
    cmd = [
        py,
        "main.py",
        "--listen",
        "127.0.0.1",
        "--port",
        str(listen_port),
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
    base_url: str | None = None,
) -> bool:
    """Poll Comfy ``/system_stats`` until up or timeout."""
    import time

    def _emit(msg: str) -> None:
        if emit:
            try:
                emit(msg)
            except Exception:  # noqa: BLE001
                pass

    url_base = (base_url or get_settings().comfy_url).rstrip("/")
    url = f"{url_base}/system_stats"
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
    # Short probes — status UI should not wait seconds when services are down.
    return {
        "api": {"url": api_url, "ok": _probe(api_url, timeout=0.4)},
        "comfy": {"url": comfy_url, "ok": _probe(comfy_url, timeout=0.4)},
        "platform": platform.system().lower(),
        "tmux_session": TMUX_SESSION if platform.system().lower() == "linux" else None,
        "logs_dir": str(LOGS_DIR),
        "torch_cuda": torch_cuda_available(),
    }


def stop_comfy() -> dict[str, Any]:
    """
    Stop Comfy on the preferred port (legacy: frees entire :8188).

    Prefer ``stop_our_comfy`` when another app may own the port.
    """
    return stop_our_comfy(port=COMFY_PORT, kill_alien=True)


def stop_our_comfy(
    *,
    port: int = COMFY_PORT,
    kill_alien: bool = False,
) -> dict[str, Any]:
    """
    Stop this repo's Comfy on ``port``.

    Never kills alien listeners unless ``kill_alien`` is True (force restart API).
    """
    notes: list[str] = []
    system = platform.system().lower()
    killed: list[int] = []

    pid_path = LOGS_DIR / "comfy.pid"
    if pid_path.is_file():
        try:
            old = int(pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            old = None
        if old and (kill_alien or is_our_comfy_pid(old)):
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
            killed.append(old)
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

    listeners = pids_listening_on(port)
    our_pids = [p for p in listeners if is_our_comfy_pid(p)]
    alien_pids = [p for p in listeners if p not in our_pids]
    if our_pids:
        killed.extend(kill_pids(our_pids))
        notes.append(f"stopped our comfy pids on {port}: {our_pids}")
    if alien_pids:
        if kill_alien:
            killed.extend(kill_pids(alien_pids))
            notes.append(f"freed port {port}: killed alien {alien_pids}")
        else:
            notes.append(
                f"port {port} still held by alien pids {alien_pids} "
                f"(left running; cmdline sample: {process_cmdline(alien_pids[0])[:80]!r})"
            )
    if not listeners:
        notes.append(f"port {port} clear")
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


def comfy_reachable(*, timeout: float = 2.0, base_url: str | None = None) -> bool:
    """True when Comfy ``/system_stats`` responds."""
    base = (base_url or get_settings().comfy_url).rstrip("/")
    return _probe(f"{base}/system_stats", timeout=timeout)


def _start_comfy_process(
    *,
    emit: Any | None = None,
    port: int | None = None,
) -> dict[str, Any]:
    """Start Comfy only; leave a healthy API process alone."""
    notes: list[str] = []

    def _note(msg: str) -> None:
        notes.append(msg)
        if emit:
            try:
                emit(msg)
            except Exception:  # noqa: BLE001
                pass

    if not COMFY_DIR.is_dir():
        raise RuntimeError(f"ComfyUI not found at {COMFY_DIR}")

    ensure_comfy_extra_local(log=_note)
    listen_port = int(port) if port is not None else COMFY_PORT
    system = platform.system().lower()
    cmd = comfy_command(port=listen_port)
    _note(f"comfy: start argv port={listen_port}")
    if system == "linux" or (system not in ("windows",) and shutil.which("tmux")):
        from photoreal.portal.supervisor_linux import start_linux

        result = start_linux(
            api_cmd=api_command(),
            comfy_cmd=cmd,
            comfy_cwd=COMFY_DIR,
            repo_root=REPO_ROOT,
        )
    elif system == "windows":
        from photoreal.portal.supervisor_windows import start_windows

        result = start_windows(
            api_cmd=api_command(),
            comfy_cmd=cmd,
            comfy_cwd=COMFY_DIR,
            repo_root=REPO_ROOT,
            logs_dir=LOGS_DIR,
        )
    else:
        raise RuntimeError(
            f"Unsupported platform {system!r}: install tmux or use Linux/Windows launchers"
        )
    for n in result.get("notes") or []:
        _note(str(n))
    result["notes"] = list(notes)
    result["port"] = listen_port
    return result


def restart_comfy(
    *,
    emit: Any | None = None,
    timeout: float = 180.0,
) -> dict[str, Any]:
    """
    Force-restart this session's Comfy on the preferred port (may free alien :8188).

    For Generate/Launch ownership-aware behavior, use ``ensure_repo_comfy``.
    """
    return ensure_repo_comfy(emit=emit, timeout=timeout, force=True)


def ensure_comfy_reachable(
    *,
    emit: Any | None = None,
    timeout: float = 180.0,
) -> dict[str, Any]:
    """Ownership-aware ensure (reuse ours, alt port if alien, restart if stale)."""
    return ensure_repo_comfy(emit=emit, timeout=timeout, force=False)


def ensure_repo_comfy(
    *,
    emit: Any | None = None,
    timeout: float = 180.0,
    force: bool = False,
) -> dict[str, Any]:
    """
    Ensure this repo has a usable ComfyUI.

    - Reuse ours on :8188 when healthy + photoreal models listed.
    - Restart ours when stale/down.
    - If alien owns :8188, start on a free alternate port (do not kill alien)
      unless ``force`` (API restart) which claims the preferred port.
    """
    import time

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    comfy_log = LOGS_DIR / "comfy.log"

    def _note(msg: str) -> None:
        notes.append(msg)
        if emit:
            try:
                emit(msg)
            except Exception:  # noqa: BLE001
                pass

    preferred = COMFY_PORT
    kind = classify_port(preferred)
    _note(f"comfy: port {preferred} class={kind}")

    if force:
        _note("comfy: force restart — stopping our (and preferred-port) listeners…")
        stop_info = stop_our_comfy(port=preferred, kill_alien=True)
        for n in stop_info.get("notes") or []:
            _note(str(n))
        for _ in range(3):
            leftovers = pids_listening_on(preferred)
            if not leftovers:
                break
            _note(f"comfy: port {preferred} still held by {leftovers}; killing…")
            free_port(preferred)
            time.sleep(0.4)
        port = preferred
        url = set_session_comfy_url(comfy_base_url(port))
        try:
            start_info = _start_comfy_process(emit=_note, port=port)
        except Exception as exc:  # noqa: BLE001
            _note(f"comfy: start failed: {exc}")
            return {
                "ok": False,
                "restarted": True,
                "reused": False,
                "port": port,
                "comfy_url": url,
                "notes": notes,
                "health": health_snapshot(),
                "logs": {"comfy": str(comfy_log)},
                "error": str(exc),
            }
        ok = wait_for_comfy(timeout=timeout, emit=emit, base_url=url)
        if ok:
            ready, missing = comfy_photoreal_models_ready(url)
            if not ready:
                _note(f"comfy: healthy but models incomplete: {missing}")
            else:
                _note("comfy: healthy after force restart (models ok)")
        else:
            _note(f"comfy: still unreachable after {timeout:.0f}s — see {comfy_log}")
        return {
            "ok": ok,
            "restarted": True,
            "reused": False,
            "port": port,
            "comfy_url": url,
            "notes": notes,
            "health": health_snapshot(),
            "logs": {"comfy": str(comfy_log)},
            "start": start_info,
            "error": None if ok else f"ComfyUI not reachable after restart — see {comfy_log}",
        }

    # --- non-force path ---
    if kind == "ours":
        url = set_session_comfy_url(comfy_base_url(preferred))
        if comfy_system_stats_ok(url):
            ready, missing = comfy_photoreal_models_ready(url)
            if ready:
                _note(f"comfy: reusing ours on {preferred} (models ok)")
                return {
                    "ok": True,
                    "restarted": False,
                    "reused": True,
                    "port": preferred,
                    "comfy_url": url,
                    "notes": notes,
                    "health": health_snapshot(),
                    "logs": {"comfy": str(comfy_log)},
                    "error": None,
                }
            _note(f"comfy: ours on {preferred} stale/missing models: {missing}")
        else:
            _note(f"comfy: ours on {preferred} not healthy — restarting")
        stop_info = stop_our_comfy(port=preferred, kill_alien=False)
        for n in stop_info.get("notes") or []:
            _note(str(n))
        port = preferred
    elif kind == "alien":
        _note(
            f"comfy: alien process on {preferred} — leaving it alone; "
            "starting this repo on another port"
        )
        try:
            port = find_free_comfy_port(preferred=preferred)
        except RuntimeError as exc:
            _note(str(exc))
            return {
                "ok": False,
                "restarted": False,
                "reused": False,
                "port": None,
                "comfy_url": None,
                "notes": notes,
                "health": health_snapshot(),
                "logs": {"comfy": str(comfy_log)},
                "error": str(exc),
            }
        if port == preferred:
            # Should not happen when alien; find next
            port = find_free_comfy_port(preferred=preferred + 1, span=11)
        _note(f"comfy: selected alternate port {port}")
    else:
        port = preferred
        _note(f"comfy: port {preferred} empty — starting ours there")

    # If we chose an alt port, ensure nothing of ours is lingering on preferred only.
    url = set_session_comfy_url(comfy_base_url(port))
    if port != preferred and classify_port(port) == "ours":
        stop_info = stop_our_comfy(port=port, kill_alien=False)
        for n in stop_info.get("notes") or []:
            _note(str(n))

    try:
        start_info = _start_comfy_process(emit=_note, port=port)
    except Exception as exc:  # noqa: BLE001
        _note(f"comfy: start failed: {exc}")
        return {
            "ok": False,
            "restarted": True,
            "reused": False,
            "port": port,
            "comfy_url": url,
            "notes": notes,
            "health": health_snapshot(),
            "logs": {"comfy": str(comfy_log)},
            "error": str(exc),
        }

    if not torch_cuda_available():
        _note("comfy: started with --cpu (PyTorch has no CUDA on this machine)")
    _note(f"comfy: waiting for /system_stats at {url}…")
    ok = wait_for_comfy(timeout=timeout, emit=emit, base_url=url)
    if ok:
        ready, missing = comfy_photoreal_models_ready(url)
        if ready:
            _note(f"comfy: healthy on port {port} (models ok)")
        else:
            _note(
                f"comfy: healthy on port {port} but models incomplete: {missing} "
                "(check comfyui_extra_model_paths.local.yaml)"
            )
    else:
        _note(f"comfy: still unreachable after {timeout:.0f}s — see {comfy_log}")

    return {
        "ok": ok,
        "restarted": True,
        "reused": False,
        "port": port,
        "comfy_url": url,
        "notes": notes,
        "health": health_snapshot(),
        "logs": {"comfy": str(comfy_log)},
        "start": start_info,
        "error": None if ok else f"ComfyUI not reachable after start — see {comfy_log}",
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

    # Always start/refresh API; Comfy via ownership-aware helper.
    if system == "linux":
        from photoreal.portal.supervisor_linux import start_linux

        result = start_linux(
            api_cmd=api_command(),
            comfy_cmd=None,
            comfy_cwd=COMFY_DIR,
            repo_root=REPO_ROOT,
        )
    elif system == "windows":
        from photoreal.portal.supervisor_windows import start_windows

        result = start_windows(
            api_cmd=api_command(),
            comfy_cmd=None,
            comfy_cwd=COMFY_DIR,
            repo_root=REPO_ROOT,
            logs_dir=LOGS_DIR,
        )
    else:
        if shutil.which("tmux"):
            from photoreal.portal.supervisor_linux import start_linux

            result = start_linux(
                api_cmd=api_command(),
                comfy_cmd=None,
                comfy_cwd=COMFY_DIR,
                repo_root=REPO_ROOT,
            )
        else:
            raise RuntimeError(
                f"Unsupported platform {system!r}: install tmux or use Linux/Windows launchers"
            )
    for n in result.get("notes") or []:
        _note(str(n))

    comfy_info: dict[str, Any] | None = None
    if want_comfy:
        comfy_info = ensure_repo_comfy(emit=_note, timeout=180.0, force=False)
        for n in comfy_info.get("notes") or []:
            if n not in notes:
                notes.append(str(n))
        if comfy_info.get("ok"):
            _note(f"Comfy ready at {comfy_info.get('comfy_url')}")
        else:
            _note(
                f"Comfy not ready — see {LOGS_DIR / 'comfy.log'} "
                f"({comfy_info.get('error')})"
            )

    result["notes"] = list(notes)
    result["health"] = health_snapshot()
    if comfy_info is not None:
        result["comfy"] = {
            "ok": comfy_info.get("ok"),
            "port": comfy_info.get("port"),
            "comfy_url": comfy_info.get("comfy_url"),
            "reused": comfy_info.get("reused"),
        }
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
