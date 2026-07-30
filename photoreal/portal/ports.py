"""Find and kill processes listening on TCP ports (Windows + Linux)."""

from __future__ import annotations

import platform
import re
import subprocess
from typing import Iterable


def pids_listening_on(port: int) -> list[int]:
    """Return PIDs bound to TCP ``port`` (LISTEN)."""
    system = platform.system().lower()
    if system == "windows":
        return _pids_windows(port)
    return _pids_linux(port)


def kill_pids(pids: Iterable[int], *, keep_pid: int | None = None) -> list[int]:
    """Kill PIDs except ``keep_pid``. Returns list of PIDs we attempted to kill."""
    killed: list[int] = []
    system = platform.system().lower()
    for pid in sorted(set(pids)):
        if pid <= 0:
            continue
        if keep_pid is not None and pid == keep_pid:
            continue
        if system == "windows":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True,
                check=False,
            )
        else:
            subprocess.run(["kill", "-TERM", str(pid)], capture_output=True, check=False)
            subprocess.run(["kill", "-KILL", str(pid)], capture_output=True, check=False)
        killed.append(pid)
    return killed


def free_port(port: int, *, keep_pid: int | None = None) -> list[int]:
    """Kill listeners on ``port`` except ``keep_pid``."""
    return kill_pids(pids_listening_on(port), keep_pid=keep_pid)


def _pids_windows(port: int) -> list[int]:
    try:
        r = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []
    pids: list[int] = []
    # Proto  Local Address  Foreign Address  State  PID
    pat = re.compile(
        rf"^\s*TCP\s+\S+:{port}\s+\S+\s+LISTENING\s+(\d+)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    for m in pat.finditer(r.stdout or ""):
        pids.append(int(m.group(1)))
    return pids


def _pids_linux(port: int) -> list[int]:
    # Prefer ss
    try:
        r = subprocess.run(
            ["ss", "-lptn", f"sport = :{port}"],
            capture_output=True,
            text=True,
            check=False,
        )
        found = re.findall(r"pid=(\d+)", r.stdout or "")
        if found:
            return [int(x) for x in found]
    except FileNotFoundError:
        pass
    # fuser -v may print PIDs on stderr
    try:
        r = subprocess.run(
            ["fuser", f"{port}/tcp"],
            capture_output=True,
            text=True,
            check=False,
        )
        text = (r.stdout or "") + " " + (r.stderr or "")
        found = re.findall(r"\b(\d+)\b", text)
        return [int(x) for x in found]
    except FileNotFoundError:
        return []
