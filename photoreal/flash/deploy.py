"""Deploy the Flash character endpoint (WSL/Linux local, or GitHub Actions on Windows)."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Callable

from photoreal.portal.credentials import apply_env_to_process, load_credentials
from photoreal.portal.paths import REPO_ROOT

LogFn = Callable[[str], None]

DEPLOY_SH = REPO_ROOT / "scripts" / "flash_deploy_character.sh"
DEPLOY_PS1 = REPO_ROOT / "scripts" / "flash_deploy_character.ps1"

# Kept for tests / messaging when GHA token is absent
WSL_NO_DISTRO_MSG = (
    "WSL has no Linux distribution installed (Flash CLI needs Linux). "
    "Preferred on this setup: save GITHUB_TOKEN on the portal and set repo "
    "Actions secrets RUNPOD_API_KEY — Generate will dispatch "
    ".github/workflows/flash-deploy-character.yml.\n"
    "Or install a distro: wsl --install -d Ubuntu (elevated PowerShell), "
    "then retry.\n"
    "See docs/portal.md"
)


def _emit(log: LogFn | None, msg: str) -> None:
    if log:
        try:
            log(msg)
        except Exception:  # noqa: BLE001
            pass


def _wsl_exe() -> str | None:
    return shutil.which("wsl") or shutil.which("wsl.exe")


def wsl_has_distro() -> bool:
    """True if ``wsl -l -q`` lists at least one distribution."""
    wsl = _wsl_exe()
    if not wsl:
        return False
    try:
        # -l -q: quiet names only. Use UTF-16LE decode — wsl.exe often emits UTF-16.
        r = subprocess.run(
            [wsl, "-l", "-q"],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    raw = r.stdout or b""
    text = ""
    for enc in ("utf-16-le", "utf-8", "utf-16"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        text = raw.decode("utf-8", errors="replace")
    # Strip NULs left from mis-decoded UTF-16
    text = text.replace("\x00", "")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # Filter noise / error banners
    bad = ("windows subsystem", "no installed", "copyright", "usage:")
    names = [ln for ln in lines if not any(b in ln.lower() for b in bad)]
    return len(names) > 0


def _looks_like_no_distro(output: str) -> bool:
    low = (output or "").lower()
    return "no installed distributions" in low or "no installed distribution" in low


def deploy_character_endpoint(*, log: LogFn | None = None, timeout_s: float = 900.0) -> None:
    """
    Run Flash deploy for photoreal-character-4090.

    Uses portal ``.env`` RUNPOD_API_KEY. On Windows without a WSL distro,
    dispatches GitHub Actions (needs ``GITHUB_TOKEN``). Otherwise runs the
    local/WSL deploy script. Streams progress into ``log``.
    """
    apply_env_to_process()
    creds = load_credentials()
    api_key = (creds.get("runpod_api_key") or "").strip()
    if not api_key:
        raise RuntimeError(
            "RUNPOD_API_KEY missing — save it on the portal before Flash deploy"
        )

    system = platform.system().lower()
    if system == "windows" and not wsl_has_distro():
        from photoreal.flash.gha_deploy import deploy_via_github_actions

        gh = (creds.get("github_token") or "").strip()
        _emit(log, "flash: no WSL distro — deploying via GitHub Actions…")
        deploy_via_github_actions(
            github_token=gh,
            log=log,
            timeout_s=max(timeout_s, 2700.0),
        )
        return

    env = os.environ.copy()
    env["RUNPOD_API_KEY"] = api_key
    hf = (creds.get("hf_token") or "").strip()
    if hf:
        env["HF_TOKEN"] = hf
    env.setdefault("FLASH_APP", "photoreal-character")
    env.setdefault("FLASH_ENV", "production")
    env["PYTHONUNBUFFERED"] = "1"

    if system == "windows":
        wsl = _wsl_exe()
        if not wsl:
            from photoreal.flash.gha_deploy import deploy_via_github_actions

            gh = (creds.get("github_token") or "").strip()
            _emit(log, "flash: WSL not found — deploying via GitHub Actions…")
            deploy_via_github_actions(
                github_token=gh,
                log=log,
                timeout_s=max(timeout_s, 2700.0),
            )
            return
        cmd = _windows_cmd(wsl)
    else:
        cmd = _unix_cmd()

    _emit(log, f"flash: deploy starting ({' '.join(cmd[:3])}…)")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Flash deploy failed to start ({exc}). "
            "On Windows without WSL: set GITHUB_TOKEN and Actions secret RUNPOD_API_KEY, "
            "or install Ubuntu via wsl --install -d Ubuntu. See docs/portal.md"
        ) from exc

    assert proc.stdout is not None
    chunks: list[str] = []
    for line in proc.stdout:
        text = line.rstrip("\n\r")
        if text:
            chunks.append(text)
            _emit(log, f"deploy: {text}")

    code = proc.wait(timeout=timeout_s)
    joined = "\n".join(chunks)
    if code != 0:
        if _looks_like_no_distro(joined):
            from photoreal.flash.gha_deploy import deploy_via_github_actions

            gh = (creds.get("github_token") or "").strip()
            _emit(log, "flash: WSL reported no distro — falling back to GitHub Actions…")
            deploy_via_github_actions(
                github_token=gh,
                log=log,
                timeout_s=max(timeout_s, 2700.0),
            )
            return
        raise RuntimeError(
            f"Flash deploy exited {code}. Fix WSL/flash login, then retry Generate "
            "or run: .\\scripts\\flash_deploy_character.ps1\n"
            "Or use GitHub Actions (docs/portal.md). "
            "Models on Network Volume photoreal-models are checked/synced on Generate "
            "(or: python scripts/flash_sync_volume.py)."
        )
    _emit(log, "flash: deploy finished ok")


def _unix_cmd() -> list[str]:
    if not DEPLOY_SH.is_file():
        raise RuntimeError(f"Missing deploy script: {DEPLOY_SH}")
    bash = shutil.which("bash") or "/bin/bash"
    return [bash, str(DEPLOY_SH)]


def _windows_cmd(wsl: str) -> list[str]:
    if not DEPLOY_PS1.is_file():
        raise RuntimeError(f"Missing deploy script: {DEPLOY_PS1}")
    drive = REPO_ROOT.drive.rstrip(":").lower()
    tail = str(REPO_ROOT).replace("\\", "/")
    if ":" in tail:
        tail = tail.split(":", 1)[1]
    wsl_root = f"/mnt/{drive}{tail}"
    inner = (
        f"cd '{wsl_root}' && "
        "sed -i 's/\\r$//' scripts/flash_deploy_character.sh && "
        "chmod +x scripts/flash_deploy_character.sh && "
        "bash scripts/flash_deploy_character.sh"
    )
    return [wsl, "-e", "bash", "-lc", inner]
