"""Linux supervisor: tmux session `photoreal` with api + comfy windows."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from photoreal.portal.supervisor import TMUX_SESSION


def _sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _shell_join(cmd: list[str]) -> str:
    return " ".join(_sh_quote(c) for c in cmd)


def _tmux(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["tmux", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _has_session() -> bool:
    r = _tmux("has-session", "-t", TMUX_SESSION, check=False)
    return r.returncode == 0


def _window_names() -> list[str]:
    if not _has_session():
        return []
    r = _tmux("list-windows", "-t", TMUX_SESSION, "-F", "#{window_name}", check=False)
    if r.returncode != 0:
        return []
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def start_linux(
    *,
    api_cmd: list[str],
    comfy_cmd: list[str] | None,
    comfy_cwd: Path,
    repo_root: Path,
) -> dict[str, Any]:
    if not shutil.which("tmux"):
        raise RuntimeError(
            "tmux is required on Linux. Install it (e.g. sudo apt install tmux)."
        )

    api_inner = (
        f"cd {_sh_quote(str(repo_root))} && "
        f"exec {_shell_join(api_cmd)}"
    )
    notes: list[str] = []

    if not _has_session():
        _tmux("new-session", "-d", "-s", TMUX_SESSION, "-n", "api", f"bash -lc {_sh_quote(api_inner)}")
        notes.append(f"created tmux session {TMUX_SESSION}")
    else:
        names = _window_names()
        if "api" not in names:
            _tmux(
                "new-window",
                "-t",
                TMUX_SESSION,
                "-n",
                "api",
                f"bash -lc {_sh_quote(api_inner)}",
            )
            notes.append("created api window")
        else:
            notes.append("api window already present (left running)")

    if comfy_cmd is not None:
        if not comfy_cwd.is_dir():
            raise RuntimeError(f"ComfyUI not found at {comfy_cwd}")
        comfy_inner = (
            f"cd {_sh_quote(str(comfy_cwd))} && "
            f"exec {_shell_join(comfy_cmd)}"
        )
        # stop_comfy() already cleared tmux window + port; create fresh
        _tmux(
            "new-window",
            "-t",
            TMUX_SESSION,
            "-n",
            "comfy",
            f"bash -lc {_sh_quote(comfy_inner)}",
        )
        notes.append("started comfy window")

    return {
        "backend": "tmux",
        "session": TMUX_SESSION,
        "attach": f"tmux attach -t {TMUX_SESSION}",
        "notes": notes,
        "windows": _window_names(),
    }
